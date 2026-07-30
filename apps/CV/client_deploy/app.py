"""AI 智慧前台数字人系统 - 模块化工程版"""

import logging
import signal
import sys
import threading
import time

import cv2

from core.async_pipeline import AsyncPipelineWrapper
from core.client_task_worker import ClientTaskWorker
from config import (
    CAMERA_INDEX,
    FRAME_WIDTH,
    FRAME_HEIGHT,
    CAMERA_BUFFER_SIZE,
    CLIENT_API_ONLY,
    ENABLE_GUI,
    DETECT_INTERVAL,
    VOTE_MIN_VOTES,
    VOTE_WINDOW,
)
from core.attendance_db import AttendanceDB
from core.daily_quote_scheduler import DailyQuoteScheduler
from core.embedding_sync import EmbeddingSyncService
from core.events import EventBus
from core.frame_hub import CameraManager, FrameConsumer, FrameHub
from core.gesture import GestureRuntime
from core.interaction_mode import MODES, load_interaction_mode
from core.recognizer import FaceRecognizer
from core.recognition_cache import RecognitionCache
from core.recognition_pipeline import RecognitionPipeline
from core.realtime_dialog import RealtimeDialogService, RealtimeDialogSettings
from core.remote_recognition import RemoteCheckInStore, RemoteRecognitionPipeline
from core.redis_checkin import RedisCheckIn
from core.shutdown import is_shutdown_requested, request_shutdown
from core.tracker import FaceTracker
from core.unknown_visitors import UnknownVisitorStore
from core.vector_db import VectorDB
from core.vote import VoteBuffer
from core.voice_system import VoiceSystem
from ui.gui import OpenCVGuiLoop

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("app")


def _run_headless_loop(
    cap,
    pipeline,
    checkin_tracker,
    gesture_runtime: GestureRuntime | None = None,
):
    logger.info(
        "无界面模式启动 (ENABLE_GUI=False)，检测间隔=%d 帧，投票窗口=%d/%d 票，摄像头静默运行中...",
        DETECT_INTERVAL,
        VOTE_WINDOW,
        VOTE_MIN_VOTES,
    )
    logger.info("按 Ctrl+C 退出")
    fps_start = time.time()
    fps_frames = 0

    frame_hub = FrameHub()
    camera_manager = CameraManager(
        cap,
        frame_hub,
        owner="app.py",
        detail="app.py headless loop",
    )
    async_pipeline = AsyncPipelineWrapper(pipeline)
    async_pipeline.start()
    camera_manager.start()
    face_consumer = FrameConsumer(
        frame_hub,
        async_pipeline.submit_frame,
        name="FaceFrameConsumer",
    )
    gesture_consumer = (
        FrameConsumer(
            frame_hub,
            gesture_runtime.submit_frame,
            name="GestureFrameConsumer",
        )
        if gesture_runtime is not None
        else None
    )
    face_consumer.start()
    if gesture_consumer is not None:
        gesture_consumer.start()

    try:
        while True:
            if is_shutdown_requested():
                logger.info("无界面模式收到退出请求")
                break
            if not camera_manager.is_alive():
                logger.error(
                    "CameraManager 已退出: %s",
                    camera_manager.last_error or "unknown",
                )
                break
            time.sleep(0.5)
            now = time.time()

            if now - fps_start >= 10.0:
                current_frames = camera_manager.frames
                fps_value = (current_frames - fps_frames) / max(
                    0.001,
                    now - fps_start,
                )
                fps_display = f"{fps_value:.1f}"
                logger.debug(
                    "FPS: %s, 今日已签: %d 人",
                    fps_display,
                    checkin_tracker.get_today_count(),
                )
                fps_frames = current_frames
                fps_start = now

    except KeyboardInterrupt:
        logger.info("收到退出信号")
        request_shutdown("keyboard_interrupt")
    finally:
        if gesture_consumer is not None:
            gesture_consumer.stop()
        face_consumer.stop()
        camera_manager.stop()
        async_pipeline.stop()


def _embedding_person_count(embeddings) -> int:
    return len({name for name, _ in embeddings})


class InteractionModeController(threading.Thread):
    """Watches the selected frontend mode and applies realtime dialog changes."""

    def __init__(self, voice_system: VoiceSystem, poll_seconds: float = 1.0):
        super().__init__(name="InteractionModeController", daemon=True)
        self.voice_system = voice_system
        self.poll_seconds = poll_seconds
        self._stop_event = threading.Event()
        self._current_mode = ""
        self._realtime_dialog: RealtimeDialogService | None = None

    def stop(self) -> None:
        self._stop_event.set()
        self.join(timeout=3)
        self._stop_realtime_dialog()

    def run(self) -> None:
        while not self._stop_event.is_set():
            mode = load_interaction_mode()
            if mode != self._current_mode:
                self._apply_mode(mode)
            self._stop_event.wait(self.poll_seconds)

    def _apply_mode(self, mode: str) -> None:
        config = MODES[mode]
        previous = self._current_mode or "未设置"
        self._current_mode = mode
        logger.info("交互链路切换: %s -> %s", previous, config.label)

        if not config.realtime_dialog:
            self._stop_realtime_dialog()
            return

        self._restart_realtime_dialog(rag_enabled=config.realtime_rag)

    def _restart_realtime_dialog(self, rag_enabled: bool) -> None:
        self._stop_realtime_dialog()
        settings = RealtimeDialogSettings(rag_enabled=rag_enabled)
        service = RealtimeDialogService(
            settings=settings,
            live2d=self.voice_system.live2d,
            voice_system=self.voice_system,
        )
        if service.start():
            self._realtime_dialog = service
            logger.info("实时语音已启用: RAG=%s", "ON" if rag_enabled else "OFF")
        else:
            logger.warning("实时语音启动失败，当前只保留 Edge-TTS 语录链路")

    def _stop_realtime_dialog(self) -> None:
        if self._realtime_dialog is None:
            return
        self._realtime_dialog.stop()
        self._realtime_dialog = None
        self.voice_system.set_realtime_dialog_active(False)
        logger.info("实时语音已停止，Edge-TTS 语录链路保持运行")

    def switch_model(self, model_key: str) -> None:
        if self._realtime_dialog is None:
            return
        self._realtime_dialog.switch_model(model_key)


def main():
    _install_shutdown_signal_handlers()
    logger.info("=" * 50)
    logger.info("AI 智慧前台数字人系统 (MVP Optimized)")
    logger.info("=" * 50)

    recognizer = FaceRecognizer()
    recognizer.init_model()

    db_embeddings = []
    vector_db = None
    if CLIENT_API_ONLY:
        logger.info("客户端 API-only 模式: 本地只采集/提特征，识别业务交给 FastAPI")
    else:
        vector_db = VectorDB()
        db_embeddings = vector_db.get_all_embeddings()
        logger.info(
            "pgvector 员工底库: %d 人 / %d 枚向量",
            _embedding_person_count(db_embeddings),
            len(db_embeddings),
        )
        if not db_embeddings:
            logger.warning("pgvector 员工底库为空，所有人脸都会进入陌生人流程")

    tracker = FaceTracker()

    attendance_db = None
    checkin_tracker = RemoteCheckInStore() if CLIENT_API_ONLY else RedisCheckIn()
    logger.info("签到去重: %s", "FastAPI" if CLIENT_API_ONLY else "Redis")

    vote_buffer = None
    rec_cache = None
    unknown_visitors = None
    if not CLIENT_API_ONLY:
        attendance_db = AttendanceDB()
        vote_buffer = VoteBuffer()
        rec_cache = RecognitionCache()
        unknown_visitors = UnknownVisitorStore()
        logger.info("未知访客记忆库: %d 人", len(unknown_visitors))

    cap = cv2.VideoCapture(CAMERA_INDEX)
    if not cap.isOpened():
        logger.error("无法打开摄像头!")
        sys.exit(1)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, CAMERA_BUFFER_SIZE)

    voice_system = VoiceSystem()
    voice_system.start()
    gesture_runtime = GestureRuntime(voice_system=voice_system)
    gesture_runtime.start()
    interaction_modes = InteractionModeController(voice_system=voice_system)
    interaction_modes.start()
    quote_scheduler = DailyQuoteScheduler(hour=6, minute=0)
    quote_scheduler.start()
    client_task_worker = ClientTaskWorker()
    client_task_worker.start()
    if CLIENT_API_ONLY:
        pipeline = RemoteRecognitionPipeline(
            recognizer=recognizer,
            tracker=tracker,
            checkin_store=checkin_tracker,
        )
        embedding_sync = None
    else:
        event_bus = EventBus(emotion_module=voice_system.emotion)
        pipeline = RecognitionPipeline(
            recognizer=recognizer,
            tracker=tracker,
            db_embeddings=db_embeddings,
            attendance_db=attendance_db,
            checkin_tracker=checkin_tracker,
            vote_buffer=vote_buffer,
            rec_cache=rec_cache,
            event_bus=event_bus,
            unknown_visitors=unknown_visitors,
        )

        embedding_sync = EmbeddingSyncService(pipeline=pipeline)
        embedding_sync.start()
        logger.info("底库实时同步服务已启动 (LISTEN/NOTIFY + 轮询兜底)")

    try:
        if ENABLE_GUI:
            OpenCVGuiLoop(
                cap,
                db_embeddings,
                pipeline,
                checkin_tracker,
                gesture_runtime=gesture_runtime,
            ).run()
        else:
            _run_headless_loop(
                cap,
                pipeline,
                checkin_tracker,
                gesture_runtime=gesture_runtime,
            )
    finally:
        logger.info("客户端开始清理资源")
        gesture_runtime.stop()
        if embedding_sync is not None:
            embedding_sync.stop()
        client_task_worker.stop()
        interaction_modes.stop()
        quote_scheduler.stop()
        pipeline.shutdown()
        voice_system.stop()
        if cap is not None:
            cap.release()
        cv2.destroyAllWindows()
        logger.info("客户端资源清理完成")


def _install_shutdown_signal_handlers() -> None:
    def _handle_signal(signum, frame) -> None:
        request_shutdown(f"signal:{signum}")

    for signum in (getattr(signal, "SIGINT", None), getattr(signal, "SIGTERM", None)):
        if signum is None:
            continue
        try:
            signal.signal(signum, _handle_signal)
        except Exception as exc:
            logger.debug("注册退出信号失败: signal=%s error=%s", signum, exc)


if __name__ == "__main__":
    main()

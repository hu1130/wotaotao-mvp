"""Realtime voice dialog service backed by Volcengine Doubao speech API."""

from __future__ import annotations

import asyncio
import json
import logging
import queue
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any

from config import (
    AVATAR_SERVER_URL,
    DEFAULT_MODEL_KEY,
    REALTIME_DIALOG_ACCESS_KEY,
    REALTIME_DIALOG_APP_KEY,
    REALTIME_DIALOG_APP_ID,
    REALTIME_DIALOG_BASE_URL,
    REALTIME_DIALOG_CITY,
    REALTIME_DIALOG_ENABLE_CUSTOM_VAD,
    REALTIME_DIALOG_ENABLE_LOUDNESS_NORM,
    REALTIME_DIALOG_END_SMOOTH_WINDOW_MS,
    REALTIME_DIALOG_INPUT_CHUNK,
    REALTIME_DIALOG_INPUT_SAMPLE_RATE,
    REALTIME_DIALOG_OUTPUT_CHUNK,
    REALTIME_DIALOG_OUTPUT_FORMAT,
    REALTIME_DIALOG_OUTPUT_SAMPLE_RATE,
    REALTIME_DIALOG_LOUDNESS_RATE,
    REALTIME_DIALOG_RELEASE_GRACE_SECONDS,
    REALTIME_DIALOG_RECV_TIMEOUT,
    REALTIME_DIALOG_RESOURCE_ID,
    REALTIME_DIALOG_MODEL,
    REALTIME_DIALOG_RAG_ENABLED,
    REALTIME_DIALOG_RAG_MAX_CHARS,
    REALTIME_DIALOG_RAG_MIN_SCORE,
    REALTIME_DIALOG_RAG_TOP_K,
    REALTIME_DIALOG_SAY_HELLO,
    REALTIME_DIALOG_SPEECH_RATE,
    REALTIME_DIALOG_VISUAL_IDLE_SECONDS,
    get_model_profile,
)
from core.avatar_state import AvatarStateCache, get_avatar_state_cache
from core.dialog_intent_router import DialogIntentRouter
from core.speech_streaming.volc_realtime import (
    VolcRealtimeDialogClient as VolcRealtimeTransport,
    VolcRealtimeDialogConfig,
)
from core.knowledge.service import KnowledgeService
from core.voice_system import Live2DController, VoiceSystem

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RealtimeDialogSettings:
    app_id: str = REALTIME_DIALOG_APP_ID
    app_key: str = REALTIME_DIALOG_APP_KEY
    access_key: str = REALTIME_DIALOG_ACCESS_KEY
    base_url: str = REALTIME_DIALOG_BASE_URL
    resource_id: str = REALTIME_DIALOG_RESOURCE_ID
    speaker: str = ""
    output_format: str = REALTIME_DIALOG_OUTPUT_FORMAT
    bot_name: str = ""
    system_role: str = ""
    speaking_style: str = ""
    city: str = REALTIME_DIALOG_CITY
    recv_timeout: int = REALTIME_DIALOG_RECV_TIMEOUT
    say_hello: bool = REALTIME_DIALOG_SAY_HELLO
    release_grace_seconds: float = REALTIME_DIALOG_RELEASE_GRACE_SECONDS
    visual_idle_seconds: float = REALTIME_DIALOG_VISUAL_IDLE_SECONDS
    input_sample_rate: int = REALTIME_DIALOG_INPUT_SAMPLE_RATE
    input_chunk: int = REALTIME_DIALOG_INPUT_CHUNK
    output_sample_rate: int = REALTIME_DIALOG_OUTPUT_SAMPLE_RATE
    output_chunk: int = REALTIME_DIALOG_OUTPUT_CHUNK
    rag_enabled: bool = REALTIME_DIALOG_RAG_ENABLED
    rag_top_k: int = REALTIME_DIALOG_RAG_TOP_K
    rag_min_score: float = REALTIME_DIALOG_RAG_MIN_SCORE
    rag_max_chars: int = REALTIME_DIALOG_RAG_MAX_CHARS
    model_key: str = DEFAULT_MODEL_KEY
    model: str = REALTIME_DIALOG_MODEL
    enable_custom_vad: bool = REALTIME_DIALOG_ENABLE_CUSTOM_VAD
    end_smooth_window_ms: int = REALTIME_DIALOG_END_SMOOTH_WINDOW_MS
    enable_loudness_norm: bool = REALTIME_DIALOG_ENABLE_LOUDNESS_NORM
    speech_rate: int = REALTIME_DIALOG_SPEECH_RATE
    loudness_rate: int = REALTIME_DIALOG_LOUDNESS_RATE

    def __post_init__(self):
        if self.speaker and self.bot_name and self.system_role and self.speaking_style:
            return
        profile = get_model_profile(self.model_key)
        object.__setattr__(self, "speaker", self.speaker or profile["speaker"])
        object.__setattr__(self, "bot_name", self.bot_name or profile["bot_name"])
        object.__setattr__(
            self, "system_role", self.system_role or profile["system_role"]
        )
        object.__setattr__(
            self, "speaking_style", self.speaking_style or profile["speaking_style"]
        )

    @property
    def ready(self) -> bool:
        return bool(self.app_id and self.app_key and self.access_key)


@dataclass(frozen=True)
class RealtimeAudioFrame:
    audio: bytes
    text: str = ""
    tts_type: str = ""
    sentence_id: int = 0


class RealtimeDialogClient:
    def __init__(self, settings: RealtimeDialogSettings, session_id: str):
        self.settings = settings
        self.session_id = session_id
        self._transport = VolcRealtimeTransport(
            VolcRealtimeDialogConfig(
                app_id=settings.app_id,
                app_key=settings.app_key,
                access_key=settings.access_key,
                base_url=settings.base_url,
                resource_id=settings.resource_id,
            ),
            start_session_payload=self._start_session_payload(),
            session_id=session_id,
        )

    @property
    def ws(self):
        return self._transport.ws

    @property
    def logid(self) -> str:
        return self._transport.logid

    async def connect(self) -> None:
        await self._transport.connect()

    def _start_session_payload(self) -> dict[str, Any]:
        return {
            "asr": {
                "extra": {
                    "enable_custom_vad": self.settings.enable_custom_vad,
                    "end_smooth_window_ms": max(
                        500, min(50000, self.settings.end_smooth_window_ms)
                    ),
                },
            },
            "tts": {
                "speaker": self.settings.speaker,
                "audio_config": {
                    "channel": 1,
                    "format": self.settings.output_format,
                    "sample_rate": self.settings.output_sample_rate,
                    "speech_rate": max(-50, min(100, self.settings.speech_rate)),
                    "loudness_rate": max(-50, min(100, self.settings.loudness_rate)),
                },
            },
            "dialog": {
                "bot_name": self.settings.bot_name,
                "system_role": self.settings.system_role,
                "speaking_style": self.settings.speaking_style,
                "location": {"city": self.settings.city},
                "extra": {
                    "strict_audit": False,
                    "audit_response": "这个问题我暂时不能回答，我们换个轻松的话题吧。",
                    "recv_timeout": self.settings.recv_timeout,
                    "input_mod": "audio",
                    "enable_loudness_norm": self.settings.enable_loudness_norm,
                    "model": self.settings.model,
                },
            },
        }

    async def say_hello(self) -> None:
        await self._transport.send_event(
            300, {"content": "你好呀，我在这里，可以直接和我说话。"}
        )

    async def send_external_rag(self, external_rag: str) -> None:
        await self._transport.send_external_rag(external_rag)

    async def send_chat_tts_text(self, text: str) -> None:
        await self._transport.send_chat_tts_text(text)

    async def send_audio(self, audio: bytes) -> None:
        await self._transport.send_audio(audio)

    async def receive(self) -> dict[str, Any]:
        return await self._transport.receive()

    async def finish_session(self) -> None:
        await self._transport.finish_session()

    async def finish_connection(self) -> None:
        await self._transport.finish_connection()

    async def close(self) -> None:
        await self._transport.close()


class AudioDevice:
    def __init__(self, settings: RealtimeDialogSettings):
        import pyaudio

        self.settings = settings
        self.pyaudio_module = pyaudio
        self.pyaudio = pyaudio.PyAudio()
        self.input_stream = None
        self.output_stream = None

    def open_input(self):
        self.input_stream = self.pyaudio.open(
            format=self.pyaudio_module.paInt16,
            channels=1,
            rate=self.settings.input_sample_rate,
            input=True,
            frames_per_buffer=self.settings.input_chunk,
        )
        return self.input_stream

    def silence_input_chunk(self) -> bytes:
        return b"\x00" * self.settings.input_chunk * 2

    def open_output(self):
        bit_size = (
            self.pyaudio_module.paInt16
            if self.settings.output_format == "pcm_s16le"
            else self.pyaudio_module.paFloat32
        )
        self.output_stream = self.pyaudio.open(
            format=bit_size,
            channels=1,
            rate=self.settings.output_sample_rate,
            output=True,
            frames_per_buffer=self.settings.output_chunk,
        )
        return self.output_stream

    def cleanup(self) -> None:
        for stream in (self.input_stream, self.output_stream):
            if stream is None:
                continue
            try:
                stream.stop_stream()
                stream.close()
            except Exception:
                pass
        self.pyaudio.terminate()


class RealtimeDialogService:
    """Owns microphone capture, realtime dialog socket, playback, and Live2D cues."""

    def __init__(
        self,
        settings: RealtimeDialogSettings | None = None,
        live2d: Live2DController | None = None,
        voice_system: VoiceSystem | None = None,
        avatar_state: AvatarStateCache | None = None,
    ):
        self.settings = settings or RealtimeDialogSettings()
        self.rag_intent_router = DialogIntentRouter(
            min_score=self.settings.rag_min_score,
            probe_knowledge=True,
            probe_top_k=self.settings.rag_top_k,
        )
        self.live2d = live2d or Live2DController(AVATAR_SERVER_URL)
        self.voice_system = voice_system
        self.avatar_state = avatar_state or get_avatar_state_cache()
        self._own_live2d = live2d is None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._audio_queue: queue.Queue[RealtimeAudioFrame | None] = queue.Queue(
            maxsize=128
        )
        self._speaking = False
        self._visible_speech_text = ""
        self._listening_active = False
        self._priority_active = False
        self._response_audio_finished = False
        self._playback_active = False
        self._playback_lock = threading.Lock()
        self._release_timer: threading.Timer | None = None
        self._visual_idle_timer: threading.Timer | None = None
        self._user_querying = False
        self._last_user_query = ""
        self._last_assistant_text = ""
        self._rag_task: asyncio.Task | None = None
        self._rag_generation = 0
        self._rag_audio_gate_generation = 0
        self._rag_pending_audio: list[RealtimeAudioFrame] = []
        self._rag_waiting_for_injected_response = False
        self._rag_gate_deadline = 0.0
        self._current_tts_type = ""
        self._current_tts_text = ""
        self._current_tts_sentence_id = 0
        self._current_tts_allowed = True
        self._visible_sentence_id = 0
        self._user_stopped = False
        self._keepalive_frames = 0
        self._last_keepalive_log_at = 0.0
        self._response_audio_frames = 0
        self._response_audio_bytes = 0
        self._played_audio_frames = 0
        self._played_audio_bytes = 0

    def start(self) -> bool:
        if not self.settings.ready:
            logger.warning("实时语音未启动: REALTIME_DIALOG_APP_ID/ACCESS_KEY 未配置")
            return False
        if self._thread and self._thread.is_alive():
            return True
        self._stop_event.clear()
        self._user_stopped = False
        if self._own_live2d:
            self.live2d.start()
        self._thread = threading.Thread(
            target=self._run_thread,
            name="RealtimeDialogThread",
            daemon=True,
        )
        self._thread.start()
        logger.info("实时语音线程已启动")
        return True

    def stop(self) -> None:
        self._user_stopped = True
        self._stop_event.set()
        if self._release_timer is not None:
            self._release_timer.cancel()
            self._release_timer = None
        if self._visual_idle_timer is not None:
            self._visual_idle_timer.cancel()
            self._visual_idle_timer = None
        try:
            self._audio_queue.put_nowait(None)
        except queue.Full:
            pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        if self._speaking:
            self._end_speech()
        if self._own_live2d:
            self.live2d.stop()

    def switch_model(self, model_key: str) -> None:
        if model_key == self.settings.model_key:
            return
        profile = get_model_profile(model_key)
        self.settings = RealtimeDialogSettings(
            speaker=profile["speaker"],
            bot_name=profile["bot_name"],
            system_role=profile["system_role"],
            speaking_style=profile["speaking_style"],
            rag_enabled=self.settings.rag_enabled,
            model_key=model_key,
        )
        self._stop_event.set()
        logger.info("实时语音切换角色: %s (%s)", profile["label"], model_key)

    def _check_model_change(self) -> None:
        state = self.avatar_state.get_ready_state(timeout_seconds=0.5)
        if state.model and state.model != self.settings.model_key:
            self.switch_model(state.model)

    def _is_avatar_audio_locked(self) -> bool:
        return self.avatar_state.is_dialog_audio_locked()

    def _is_realtime_output_active(self) -> bool:
        with self._playback_lock:
            playback_active = self._playback_active
        return playback_active or not self._audio_queue.empty() or self._speaking

    def _run_thread(self) -> None:
        delay = 3.0
        first_run = True
        while not self._user_stopped:
            self._check_model_change()
            try:
                self._stop_event.clear()
                asyncio.run(self._run(say_hello=first_run))
                first_run = False
                delay = 3.0
                if self._user_stopped:
                    break
                logger.info("实时语音会话正常结束, %0.1f 秒后重新连接", delay)
            except Exception as exc:
                if self._user_stopped:
                    break
                logger.warning("实时语音连接异常: %s, %0.1f 秒后重连", exc, delay)
            if self._stop_event.wait(timeout=delay) and self._user_stopped:
                break
            delay = min(delay * 1.5, 30.0)
        logger.info("实时语音服务已停止")

    async def _run(self, say_hello: bool = True) -> None:
        self._clear_pending_audio()
        audio_device = AudioDevice(self.settings)
        client = RealtimeDialogClient(self.settings, session_id=str(uuid.uuid4()))
        player = threading.Thread(
            target=self._playback_loop,
            args=(audio_device,),
            name="RealtimeDialogPlayer",
            daemon=True,
        )
        try:
            audio_device.open_output()
            audio_device.open_input()
            player.start()
            await client.connect()
            if say_hello and self.settings.say_hello:
                await client.say_hello()
            await asyncio.gather(
                self._microphone_loop(audio_device, client),
                self._receive_loop(client),
            )
        finally:
            try:
                await client.finish_session()
                await client.finish_connection()
            except Exception:
                pass
            await client.close()
            self._audio_queue.put(None)
            player.join(timeout=3)
            audio_device.cleanup()
            self._reset_session_runtime_state("session closed")
            logger.info("实时语音会话已关闭 logid=%s", client.logid)

    async def _microphone_loop(
        self,
        audio_device: AudioDevice,
        client: RealtimeDialogClient,
    ) -> None:
        logger.info("实时语音麦克风已打开，可以开始讲话")
        while not self._stop_event.is_set():
            try:
                self._check_model_change()
                if self._stop_event.is_set():
                    break
                avatar_locked = self._is_avatar_audio_locked()
                output_active = self._is_realtime_output_active()
                if avatar_locked or output_active:
                    await self._send_silence_keepalive(
                        audio_device,
                        client,
                        avatar_locked=avatar_locked,
                        output_active=output_active,
                    )
                    continue
                audio = audio_device.input_stream.read(
                    self.settings.input_chunk,
                    exception_on_overflow=False,
                )
                await client.send_audio(audio)
                await asyncio.sleep(0.01)
            except Exception as exc:
                logger.warning("实时语音麦克风读取失败: %s", exc)
                await asyncio.sleep(0.1)

    async def _send_silence_keepalive(
        self,
        audio_device: AudioDevice,
        client: RealtimeDialogClient,
        *,
        avatar_locked: bool,
        output_active: bool,
    ) -> None:
        try:
            if audio_device.input_stream is not None:
                audio_device.input_stream.read(
                    self.settings.input_chunk,
                    exception_on_overflow=False,
                )
        except Exception as exc:
            logger.debug("实时语音隔离期麦克风丢弃失败: %s", exc)
        if self._stop_event.is_set():
            return
        await client.send_audio(audio_device.silence_input_chunk())
        self._keepalive_frames += 1
        now = time.monotonic()
        if now - self._last_keepalive_log_at >= 5.0:
            self._last_keepalive_log_at = now
            logger.info(
                "实时语音隔离保活: frames=%s avatar_locked=%s output_active=%s speaking=%s queue=%s",
                self._keepalive_frames,
                avatar_locked,
                output_active,
                self._speaking,
                self._audio_queue.qsize(),
            )
        await asyncio.sleep(0.01)

    async def _receive_loop(self, client: RealtimeDialogClient) -> None:
        while not self._stop_event.is_set():
            try:
                response = await asyncio.wait_for(client.receive(), timeout=0.5)
            except asyncio.TimeoutError:
                self._release_expired_rag_audio_gate()
                continue
            await self._handle_response(response, client)
            event = response.get("event")
            if event in {152, 153}:
                self._stop_event.set()
                break

    async def _handle_response(
        self, response: dict[str, Any], client: RealtimeDialogClient
    ) -> None:
        if not response:
            return
        self._release_expired_rag_audio_gate()

        if response.get("message_type") == "SERVER_ACK" and isinstance(
            response.get("payload_msg"), bytes
        ):
            self._response_audio_frames += 1
            self._response_audio_bytes += len(response["payload_msg"])
            frame = RealtimeAudioFrame(
                audio=response["payload_msg"],
                text=self._current_tts_text,
                tts_type=self._current_tts_type,
                sentence_id=self._current_tts_sentence_id,
            )
            if self._hold_audio_until_rag_ready(frame):
                return
            if not self._speaking:
                self._activate_priority()
                self._response_audio_finished = False
            self._enqueue_audio(frame)
            return

        if response.get("message_type") == "SERVER_ERROR":
            logger.error("实时语音服务错误: %s", response.get("payload_msg"))
            self._stop_event.set()
            return

        event = response.get("event")
        payload = response.get("payload_msg")
        query = self._extract_user_query(payload)
        if query:
            self._last_user_query = query
        assistant_text = (
            self._extract_assistant_text(payload) if event in {350, 351, 359} else ""
        )
        if event == 350:
            self._handle_tts_sentence_start(payload, assistant_text)
        elif assistant_text and assistant_text != self._last_assistant_text:
            self._last_assistant_text = assistant_text

        if event == 450:
            self._user_querying = True
            self._rag_generation += 1
            self._reset_audio_counters()
            if self._rag_task is not None and not self._rag_task.done():
                self._rag_task.cancel()
            self._last_assistant_text = ""
            self._current_tts_text = ""
            self._current_tts_type = ""
            self._current_tts_sentence_id = 0
            if self.settings.rag_enabled:
                self._start_rag_audio_gate(self._rag_generation)
            else:
                self._clear_rag_audio_gate()
            self._activate_priority()
            self._response_audio_finished = False
            self._clear_pending_audio()
            self._end_visual_speech()
            self._show_listening()
        elif event == 459:
            self._user_querying = False
            self._end_listening()
            await self._trigger_external_rag(client)
        elif event == 359:
            if self._rag_waiting_for_injected_response:
                if self._current_tts_type == "default":
                    self._current_tts_type = ""
                    self._current_tts_text = ""
                    self._current_tts_sentence_id = 0
                    self._current_tts_allowed = True
                    return
                self._finish_rag_audio_gate(
                    self._rag_generation,
                    replay_pending=False,
                    clear_visual=False,
                )
            self._current_tts_type = ""
            self._current_tts_text = ""
            self._current_tts_sentence_id = 0
            self._current_tts_allowed = True
            self._response_audio_finished = True
            logger.info(
                "实时语音回复音频接收完成: frames=%s bytes=%s played_frames=%s played_bytes=%s queue=%s",
                self._response_audio_frames,
                self._response_audio_bytes,
                self._played_audio_frames,
                self._played_audio_bytes,
                self._audio_queue.qsize(),
            )
            self._release_priority_when_playback_idle()
        elif response.get("message_type") == "SERVER_FULL_RESPONSE":
            logger.debug("实时语音事件: %s", response)

    async def _trigger_external_rag(self, client: RealtimeDialogClient) -> None:
        if not self.settings.rag_enabled:
            return
        query = self._last_user_query.strip()
        if not query:
            logger.info("实时语音 RAG 跳过: 未从事件 payload 中提取到用户问题")
            self._finish_rag_audio_gate(self._rag_generation, replay_pending=True)
            return
        generation = self._rag_generation
        self._start_rag_audio_gate(generation)
        if self._rag_task is not None and not self._rag_task.done():
            self._rag_task.cancel()
        self._rag_task = asyncio.create_task(
            self._send_external_rag_for_query(client, query, generation)
        )

    async def _send_external_rag_for_query(
        self,
        client: RealtimeDialogClient,
        query: str,
        generation: int,
    ) -> None:
        try:
            route_started_at = time.perf_counter()
            intent_route = await asyncio.to_thread(
                self.rag_intent_router.route,
                query,
            )
            logger.info(
                "实时语音 RAG 意图路由: route=%s intent=%s reason=%s confidence=%.3f probe_min=%.3f route_ms=%.0f query=%s",
                intent_route.route,
                intent_route.intent,
                intent_route.reason,
                intent_route.confidence,
                intent_route.knowledge_min_score,
                (time.perf_counter() - route_started_at) * 1000,
                query,
            )
            if not intent_route.use_knowledge:
                self._finish_rag_audio_gate(generation, replay_pending=True)
                return
            external_rag = await asyncio.to_thread(
                self._build_external_rag,
                query,
                intent_route.results if intent_route.knowledge_probed else None,
            )
            if not external_rag:
                self._finish_rag_audio_gate(generation, replay_pending=True)
                return
            if (
                self._stop_event.is_set()
                or self._user_querying
                or generation != self._rag_generation
            ):
                logger.debug("实时语音 RAG 丢弃: 会话已进入新一轮 query=%s", query)
                return
            await client.send_external_rag(external_rag)
            self._clear_pending_audio()
            self._rag_pending_audio.clear()
            self._rag_waiting_for_injected_response = True
            self._rag_gate_deadline = time.monotonic() + 6.0
            logger.info("实时语音 RAG 已注入: query=%s", query)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._finish_rag_audio_gate(generation, replay_pending=True)
            logger.warning("实时语音 RAG 注入失败: %s", exc)

    def _start_rag_audio_gate(self, generation: int) -> None:
        if self._rag_audio_gate_generation != generation:
            self._rag_pending_audio.clear()
        self._rag_audio_gate_generation = generation
        self._rag_waiting_for_injected_response = False

    def _clear_rag_audio_gate(self) -> None:
        self._rag_audio_gate_generation = 0
        self._rag_pending_audio.clear()
        self._rag_waiting_for_injected_response = False
        self._rag_gate_deadline = 0.0

    def _handle_tts_sentence_start(self, payload: Any, text: str) -> None:
        tts_type = self._extract_tts_type(payload)
        self._current_tts_type = tts_type
        self._current_tts_text = text or ""
        self._current_tts_sentence_id += 1
        if text and text != self._last_assistant_text:
            self._last_assistant_text = text
        if (
            self._rag_audio_gate_generation > 0
            and self._rag_audio_gate_generation == self._rag_generation
        ):
            if tts_type in {"external_rag", "chat_tts_text"}:
                self._current_tts_allowed = True
                self._finish_rag_audio_gate(
                    self._rag_generation,
                    replay_pending=False,
                    clear_visual=False,
                )
            elif tts_type == "default":
                self._current_tts_allowed = False
            else:
                self._current_tts_allowed = True
        else:
            self._current_tts_allowed = True

    def _hold_audio_until_rag_ready(self, frame: RealtimeAudioFrame) -> bool:
        if (
            not self.settings.rag_enabled
            or self._rag_audio_gate_generation <= 0
            or self._rag_audio_gate_generation != self._rag_generation
        ):
            return False
        if len(self._rag_pending_audio) >= 128:
            self._rag_pending_audio.pop(0)
        self._rag_pending_audio.append(frame)
        return True

    def _should_drop_current_audio(self) -> bool:
        return (
            self._rag_audio_gate_generation > 0
            and self._rag_audio_gate_generation == self._rag_generation
            and not self._current_tts_allowed
        )

    def _finish_rag_audio_gate(
        self,
        generation: int,
        *,
        replay_pending: bool,
        clear_visual: bool = True,
    ) -> None:
        if generation != self._rag_audio_gate_generation:
            return
        pending = list(self._rag_pending_audio)
        self._clear_rag_audio_gate()
        if not replay_pending:
            if clear_visual:
                self._last_assistant_text = ""
                self._end_visual_speech()
            return
        for frame in pending:
            self._enqueue_audio(frame)

    def _release_expired_rag_audio_gate(self) -> None:
        if (
            self._rag_waiting_for_injected_response
            and self._rag_gate_deadline > 0
            and time.monotonic() >= self._rag_gate_deadline
        ):
            logger.warning("实时语音 RAG 注入后等待新回复超时，放行兜底音频")
            self._finish_rag_audio_gate(self._rag_generation, replay_pending=True)

    def _enqueue_audio(self, frame: RealtimeAudioFrame) -> None:
        try:
            self._audio_queue.put_nowait(frame)
        except queue.Full:
            logger.debug("实时语音播放队列已满，丢弃一段音频")

    def _build_external_rag(
        self,
        query: str,
        precomputed_results: list[Any] | None = None,
    ) -> str:
        retrieval_source = (
            "intent_probe" if precomputed_results is not None else "direct"
        )
        results = list(precomputed_results or [])
        if precomputed_results is None:
            results = KnowledgeService().search(
                query,
                top_k=self.settings.rag_top_k,
                min_score=self.settings.rag_min_score,
            )
        if not results:
            logger.info(
                "实时语音 RAG 无命中: query=%s retrieval=%s",
                query,
                retrieval_source,
            )
            return ""

        items = []
        used = 0
        for result in results:
            title = result.title or result.source_path
            content = result.content.strip()
            remaining = self.settings.rag_max_chars - used
            if remaining <= 0:
                break
            if len(content) > remaining:
                content = content[:remaining]
            items.append({"title": title, "content": content})
            used += len(content)
        logger.info(
            "实时语音 RAG 命中: query=%s hits=%s retrieval=%s",
            query,
            len(items),
            retrieval_source,
        )
        return json.dumps(items, ensure_ascii=False)

    def _extract_user_query(self, payload: Any) -> str:
        if not isinstance(payload, (dict, list)):
            return ""
        preferred_keys = {
            "query",
            "text",
            "content",
            "asr_text",
            "asr",
            "utterance",
            "transcript",
            "user_query",
            "input_text",
        }

        def walk(value: Any) -> str:
            if isinstance(value, dict):
                for key in preferred_keys:
                    item = value.get(key)
                    if isinstance(item, str) and item.strip():
                        return item.strip()
                for item in value.values():
                    found = walk(item)
                    if found:
                        return found
            elif isinstance(value, list):
                for item in value:
                    found = walk(item)
                    if found:
                        return found
            return ""

        return walk(payload)

    def _extract_tts_type(self, payload: Any) -> str:
        if not isinstance(payload, (dict, list)):
            return ""

        def walk(value: Any) -> str:
            if isinstance(value, dict):
                item = value.get("tts_type")
                if isinstance(item, str) and item.strip():
                    return item.strip()
                for child in value.values():
                    found = walk(child)
                    if found:
                        return found
            elif isinstance(value, list):
                for child in value:
                    found = walk(child)
                    if found:
                        return found
            return ""

        return walk(payload)

    def _extract_assistant_text(self, payload: Any) -> str:
        if not isinstance(payload, (dict, list)):
            return ""
        preferred_keys = {
            "answer",
            "assistant_text",
            "bot_text",
            "response",
            "response_text",
            "output_text",
            "tts_text",
            "speech_text",
            "text",
            "content",
        }

        def walk(value: Any) -> str:
            if isinstance(value, dict):
                for key in preferred_keys:
                    item = value.get(key)
                    if isinstance(item, str) and item.strip():
                        return item.strip()
                for item in value.values():
                    found = walk(item)
                    if found:
                        return found
            elif isinstance(value, list):
                for item in value:
                    found = walk(item)
                    if found:
                        return found
            return ""

        return walk(payload)

    def _playback_loop(self, audio_device: AudioDevice) -> None:
        while not self._stop_event.is_set():
            try:
                frame = self._audio_queue.get(timeout=1)
            except queue.Empty:
                continue
            if frame is None:
                break
            try:
                while not self._stop_event.is_set() and self._is_avatar_audio_locked():
                    time.sleep(0.05)
                if self._stop_event.is_set():
                    break
                with self._playback_lock:
                    self._playback_active = True
                self._start_speech(frame.text, frame.sentence_id)
                audio_device.output_stream.write(frame.audio)
                self._played_audio_frames += 1
                self._played_audio_bytes += len(frame.audio)
            except Exception as exc:
                logger.warning("实时语音播放失败 (%s): %s", frame.tts_type, exc)
            finally:
                with self._playback_lock:
                    self._playback_active = False
                self._audio_queue.task_done()
                self._release_priority_when_playback_idle()
                self._schedule_visual_idle_watchdog()

    def _clear_pending_audio(self) -> None:
        while True:
            try:
                self._audio_queue.get_nowait()
                self._audio_queue.task_done()
            except queue.Empty:
                break

    def _show_listening(self) -> None:
        self._listening_active = True
        self.live2d.enqueue(
            "speech",
            {
                "event_type": "realtime_dialog",
                "name": self.settings.bot_name,
                "text": "我在听呢～",
                "listening": True,
            },
        )

    def _end_listening(self) -> None:
        if not self._listening_active:
            return
        self._listening_active = False
        self.live2d.enqueue(
            "speech_end",
            {"event_type": "realtime_dialog", "listening": True},
        )

    def _start_speech(self, text: str = "", sentence_id: int = 0) -> None:
        self._activate_priority()
        self._listening_active = False
        if self._visual_idle_timer is not None:
            self._visual_idle_timer.cancel()
            self._visual_idle_timer = None
        display_text = text or self._last_assistant_text or "正在和你实时对话..."
        if (
            display_text != self._visible_speech_text
            or sentence_id != self._visible_sentence_id
        ):
            self._update_visual_speech(display_text, sentence_id)

    def _update_visual_speech(self, text: str, sentence_id: int = 0) -> None:
        self._speaking = True
        self._visible_speech_text = text
        self._visible_sentence_id = sentence_id
        self.live2d.enqueue(
            "speech",
            {
                "event_type": "realtime_dialog",
                "name": self.settings.bot_name,
                "text": text,
                "external_audio": True,
            },
        )

    def _end_speech(self) -> None:
        if self._visual_idle_timer is not None:
            self._visual_idle_timer.cancel()
            self._visual_idle_timer = None
        logger.info(
            "实时语音播放收尾: speaking=%s visible_text=%s received_frames=%s played_frames=%s received_bytes=%s played_bytes=%s queue=%s",
            self._speaking,
            self._visible_speech_text,
            self._response_audio_frames,
            self._played_audio_frames,
            self._response_audio_bytes,
            self._played_audio_bytes,
            self._audio_queue.qsize(),
        )
        self._end_visual_speech()
        self._deactivate_priority()

    def _end_visual_speech(self) -> None:
        if not self._speaking:
            return
        self._speaking = False
        self._visible_speech_text = ""
        self._visible_sentence_id = 0
        self.live2d.enqueue("speech_end", {"event_type": "realtime_dialog"})

    def _activate_priority(self) -> None:
        if self._release_timer is not None:
            self._release_timer.cancel()
            self._release_timer = None
        if self._priority_active:
            return
        self._priority_active = True
        if self.voice_system is not None:
            self.voice_system.set_realtime_dialog_active(True)

    def _deactivate_priority(self) -> None:
        if not self._priority_active:
            return
        self._priority_active = False
        if self.voice_system is not None:
            self.voice_system.set_realtime_dialog_active(False)

    def _release_priority_when_playback_idle(self) -> None:
        if not self._response_audio_finished or not self._priority_active:
            return
        with self._playback_lock:
            playback_active = self._playback_active
        if playback_active or not self._audio_queue.empty():
            return
        if self._release_timer is not None:
            self._release_timer.cancel()
        self._release_timer = threading.Timer(
            self.settings.release_grace_seconds,
            self._release_priority_if_still_idle,
        )
        self._release_timer.daemon = True
        self._release_timer.start()

    def _release_priority_if_still_idle(self) -> None:
        with self._playback_lock:
            playback_active = self._playback_active
        if playback_active or not self._audio_queue.empty():
            return
        self._end_speech()

    def _schedule_visual_idle_watchdog(self) -> None:
        if self._visual_idle_timer is not None:
            self._visual_idle_timer.cancel()
        if not self._speaking or not self._audio_queue.empty():
            return
        self._visual_idle_timer = threading.Timer(
            self.settings.visual_idle_seconds,
            self._end_speech_if_audio_idle,
        )
        self._visual_idle_timer.daemon = True
        self._visual_idle_timer.start()

    def _end_speech_if_audio_idle(self) -> None:
        with self._playback_lock:
            playback_active = self._playback_active
        if playback_active or not self._audio_queue.empty():
            return
        logger.warning("实时语音播放已空闲但未收到完整结束事件，主动收尾")
        self._end_speech()

    def _reset_session_runtime_state(self, reason: str) -> None:
        if self._release_timer is not None:
            self._release_timer.cancel()
            self._release_timer = None
        if self._visual_idle_timer is not None:
            self._visual_idle_timer.cancel()
            self._visual_idle_timer = None
        had_visual_state = self._speaking or self._listening_active
        had_priority = self._priority_active
        with self._playback_lock:
            self._playback_active = False
        self._clear_pending_audio()
        self._speaking = False
        self._visible_speech_text = ""
        self._visible_sentence_id = 0
        self._listening_active = False
        self._priority_active = False
        self._response_audio_finished = False
        self._user_querying = False
        self._current_tts_type = ""
        self._current_tts_text = ""
        self._current_tts_sentence_id = 0
        self._current_tts_allowed = True
        self._clear_rag_audio_gate()
        if had_visual_state:
            self.live2d.enqueue("speech_end", {"event_type": "realtime_dialog"})
        if had_priority and self.voice_system is not None:
            self.voice_system.set_realtime_dialog_active(False)
        logger.info(
            "实时语音会话运行态已复位: reason=%s had_visual=%s had_priority=%s keepalive_frames=%s",
            reason,
            had_visual_state,
            had_priority,
            self._keepalive_frames,
        )
        self._keepalive_frames = 0
        self._last_keepalive_log_at = 0.0
        self._reset_audio_counters()

    def _reset_audio_counters(self) -> None:
        self._response_audio_frames = 0
        self._response_audio_bytes = 0
        self._played_audio_frames = 0
        self._played_audio_bytes = 0

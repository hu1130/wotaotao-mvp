"""Threaded gesture recognition runtime fed by the existing camera loop."""

from __future__ import annotations

import logging
import threading
import time

from config import (
    GESTURE_ENABLED,
    GESTURE_ENTRY_GRACE_SECONDS,
    GESTURE_FRAME_INTERVAL,
    GESTURE_STAGE,
    GESTURE_TARGET_FPS,
    GESTURE_TRIGGER_MAX_MOTION,
)
from core.gesture.classifier import StaticGestureClassifier
from core.gesture.avatar_responder import GestureAvatarResponder
from core.gesture.detector import GestureDependencyError, MediaPipeHandDetector
from core.gesture.event_manager import GestureEventManager
from core.gesture.schemas import GestureCandidate, GestureEvent, NO_GESTURE
from core.gesture.status import GestureStatusWriter
from core.gesture.temporal import StaticGestureStabilizer
from core.voice_system import VoiceSystem

logger = logging.getLogger(__name__)


class GestureRuntime:
    """Runs hand gesture recognition in a side thread without owning the camera."""

    def __init__(
        self,
        enabled: bool = GESTURE_ENABLED,
        stage: str = GESTURE_STAGE,
        voice_system: VoiceSystem | None = None,
    ):
        self.enabled = enabled
        self.stage = stage
        self.voice_system = voice_system
        self._stop_event = threading.Event()
        self._frame_ready = threading.Event()
        self._frame_lock = threading.Lock()
        self._latest_frame = None
        self._thread: threading.Thread | None = None
        self._submitted_frames = 0
        self._processed_frames = 0
        self._last_submit_at = 0.0
        self._min_submit_interval = 1.0 / max(1.0, GESTURE_TARGET_FPS)
        self._started_at = time.time()
        self._no_hand_streak = 0
        self._last_no_hand_log_at = 0.0
        self._active_hands: set[str] = set()
        self._hand_first_seen_at: dict[str, float] = {}
        self.status = GestureStatusWriter()

    def start(self) -> None:
        if not self.enabled:
            self.status.write(
                enabled=False,
                running=False,
                stage=self.stage,
                force=True,
            )
            logger.info("手势识别未启用 (GESTURE_ENABLED=0)")
            return
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run,
            name="GestureRuntime",
            daemon=True,
        )
        self._thread.start()
        logger.info("手势识别线程已启动: stage=%s", self.stage)

    def stop(self) -> None:
        self._stop_event.set()
        self._frame_ready.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        self.status.write(
            enabled=self.enabled,
            running=False,
            stage=self.stage,
            force=True,
        )
        if self.enabled:
            logger.info(
                "手势识别线程已停止 (提交=%d, 处理=%d)",
                self._submitted_frames,
                self._processed_frames,
            )

    def submit_frame(self, frame) -> None:
        if not self.enabled:
            return
        self._submitted_frames += 1
        if self._submitted_frames % max(1, GESTURE_FRAME_INTERVAL) != 0:
            return
        now = time.time()
        if now - self._last_submit_at < self._min_submit_interval:
            return
        self._last_submit_at = now
        with self._frame_lock:
            self._latest_frame = frame.copy()
            self._frame_ready.set()

    def _run(self) -> None:
        try:
            detector = MediaPipeHandDetector()
        except GestureDependencyError as exc:
            logger.warning("%s", exc)
            self.status.write(
                enabled=True,
                running=False,
                stage=self.stage,
                error=str(exc),
                force=True,
            )
            return

        classifier = StaticGestureClassifier()
        static_stabilizer = StaticGestureStabilizer()
        event_manager = GestureEventManager(self.stage)
        responder = (
            GestureAvatarResponder(self.voice_system, self.stage)
            if self.voice_system is not None
            else None
        )
        last_candidate: GestureCandidate | None = None
        last_event: GestureEvent | None = None

        self.status.write(
            enabled=True,
            running=True,
            stage=self.stage,
            force=True,
        )
        try:
            while not self._stop_event.is_set():
                frame = self._take_latest_frame()
                if frame is None:
                    continue

                try:
                    observations = detector.detect(frame)
                    observed_hands = {
                        observation.handedness for observation in observations
                    }
                    gone_hands = self._active_hands - observed_hands
                    candidate = self._classify_frame(
                        observations,
                        classifier,
                        static_stabilizer,
                    )
                    if observed_hands:
                        for gone_hand in gone_hands:
                            event_manager.clear_hand(gone_hand, "hand_lost")
                    else:
                        event_manager.clear_all("no_hands")
                    if candidate is not None:
                        self._no_hand_streak = 0
                        last_candidate = candidate
                        event = None
                        if self._should_update_event_manager(candidate, responder):
                            event = event_manager.update(candidate)
                        else:
                            logger.debug(
                                "GESTURE 事件等待实时语音结束: candidate=%s hand=%s phase=%s",
                                candidate.name,
                                candidate.hand,
                                (candidate.metadata or {}).get("phase", ""),
                            )
                        if event is not None:
                            last_event = event
                            if responder is not None:
                                responder.handle_event(event)
                            logger.info(
                                "GESTURE | %s | hand=%s confidence=%.2f stage=%s action=%s",
                                event.name,
                                event.hand,
                                event.confidence,
                                event.stage,
                                event.action_mode,
                            )
                        self.status.write(
                            enabled=True,
                            running=True,
                            stage=self.stage,
                            candidate=last_candidate,
                            stable_candidate=event_manager.stable_candidate,
                            event=last_event,
                            diagnostics=self._diagnostics(
                                hand_count=len(observations),
                                candidate=last_candidate,
                            ),
                        )
                    else:
                        hand_count = len(observations)
                        if hand_count == 0:
                            self._no_hand_streak += 1
                            self._log_no_hands_if_needed()
                        else:
                            self._no_hand_streak = 0
                        last_candidate = None
                        self.status.write(
                            enabled=True,
                            running=True,
                            stage=self.stage,
                            candidate=None,
                            stable_candidate=event_manager.stable_candidate,
                            event=last_event,
                            diagnostics=self._diagnostics(
                                hand_count=hand_count,
                                candidate=None,
                            ),
                        )
                    self._processed_frames += 1
                except Exception as exc:
                    logger.exception("手势识别帧处理异常: %s", exc)
                    last_candidate = None
                    self.status.write(
                        enabled=True,
                        running=True,
                        stage=self.stage,
                        candidate=None,
                        stable_candidate=event_manager.stable_candidate,
                        event=last_event,
                        diagnostics=self._diagnostics(
                            hand_count=0,
                            candidate=None,
                        ),
                        error=str(exc),
                        force=True,
                    )
                    time.sleep(0.5)
        finally:
            detector.close()

    def _take_latest_frame(self):
        self._frame_ready.wait(timeout=0.2)
        with self._frame_lock:
            frame = self._latest_frame
            self._latest_frame = None
            self._frame_ready.clear()
        return frame

    def _classify_frame(
        self,
        observations,
        classifier: StaticGestureClassifier,
        static_stabilizer: StaticGestureStabilizer,
    ) -> GestureCandidate | None:
        now = time.time()
        best_actionable: GestureCandidate | None = None
        best_debug: GestureCandidate | None = None
        current_hands: set[str] = set()
        for observation in observations:
            current_hands.add(observation.handedness)
            first_seen_at = self._hand_first_seen_at.setdefault(
                observation.handedness,
                now,
            )
            static_candidate = classifier.classify(observation)
            if static_candidate.name == "open_hand":
                open_hand_candidate = static_stabilizer.update(
                    observation,
                    static_candidate,
                )
                if open_hand_candidate.metadata.get("phase") == "complete":
                    candidate = self._open_hand_wave_candidate(open_hand_candidate)
                else:
                    candidate = self._open_hand_tracking_candidate(open_hand_candidate)
            else:
                candidate = static_stabilizer.update(
                    observation,
                    static_candidate,
                )
            candidate = self._gate_transient_candidate(
                candidate,
                first_seen_at=first_seen_at,
                now=now,
            )
            if candidate is None:
                continue
            if best_debug is None or candidate.confidence > best_debug.confidence:
                best_debug = candidate
            if candidate.metadata.get("suppress_event"):
                continue
            if (
                best_actionable is None
                or candidate.confidence > best_actionable.confidence
            ):
                best_actionable = candidate
        for gone in self._active_hands - current_hands:
            static_stabilizer.remove_hand(gone)
            self._hand_first_seen_at.pop(gone, None)
        self._active_hands = current_hands
        return best_actionable or best_debug

    @staticmethod
    def _gate_transient_candidate(
        candidate: GestureCandidate,
        *,
        first_seen_at: float,
        now: float,
    ) -> GestureCandidate:
        metadata = dict(candidate.metadata or {})
        if (
            candidate.name == NO_GESTURE
            or metadata.get("suppress_event")
            or metadata.get("phase") in {"none", "moving", "settling"}
        ):
            return candidate

        hand_age = max(0.0, now - first_seen_at)
        if hand_age < GESTURE_ENTRY_GRACE_SECONDS:
            return GestureRuntime._suppress_candidate(
                candidate,
                metadata,
                reason="entry_grace",
                hand_age=hand_age,
            )

        motion = metadata.get("motion")
        if isinstance(motion, (int, float)) and motion > GESTURE_TRIGGER_MAX_MOTION:
            return GestureRuntime._suppress_candidate(
                candidate,
                metadata,
                reason="fast_motion",
                hand_age=hand_age,
            )
        return candidate

    @staticmethod
    def _suppress_candidate(
        candidate: GestureCandidate,
        metadata: dict,
        *,
        reason: str,
        hand_age: float,
    ) -> GestureCandidate:
        metadata.update(
            {
                "suppress_event": True,
                "suppress_reason": reason,
                "hand_age_seconds": round(hand_age, 3),
            }
        )
        logger.debug(
            "GESTURE 触发抑制: hand=%s gesture=%s reason=%s age=%.3f motion=%s",
            candidate.hand,
            candidate.name,
            reason,
            hand_age,
            metadata.get("motion"),
        )
        return GestureCandidate(
            name=candidate.name,
            confidence=candidate.confidence,
            hand=candidate.hand,
            metadata=metadata,
        )

    @staticmethod
    def _should_update_event_manager(
        candidate: GestureCandidate,
        responder: GestureAvatarResponder | None,
    ) -> bool:
        if responder is None or not responder.is_realtime_priority_active():
            return True
        metadata = candidate.metadata or {}
        phase = metadata.get("phase", "")
        return (
            candidate.name == NO_GESTURE
            or bool(metadata.get("suppress_event"))
            or phase in {"moving", "settling", "none", "tracking_wave"}
        )

    @staticmethod
    def _open_hand_tracking_candidate(
        candidate: GestureCandidate,
    ) -> GestureCandidate:
        metadata = dict(candidate.metadata or {})
        metadata.update(
            {
                "phase": "tracking_wave",
                "suppress_event": True,
            }
        )
        return GestureCandidate(
            name=candidate.name,
            confidence=candidate.confidence,
            hand=candidate.hand,
            metadata=metadata,
        )

    @staticmethod
    def _open_hand_wave_candidate(
        candidate: GestureCandidate,
    ) -> GestureCandidate:
        metadata = dict(candidate.metadata or {})
        metadata.update(
            {
                "phase": "complete",
                "model_label": "open_hand",
                "trigger": "open_hand_as_wave",
            }
        )
        return GestureCandidate(
            name="wave",
            confidence=candidate.confidence,
            hand=candidate.hand,
            metadata=metadata,
        )

    def _diagnostics(
        self,
        *,
        hand_count: int,
        candidate: GestureCandidate | None,
    ) -> dict:
        metadata = candidate.metadata if candidate is not None else {}
        return {
            "hands": hand_count,
            "candidate_phase": metadata.get("phase") if metadata else "",
            "candidate_motion": metadata.get("motion") if metadata else None,
            "candidate_suppress_reason": metadata.get("suppress_reason")
            if metadata
            else "",
            "hand_age_seconds": metadata.get("hand_age_seconds") if metadata else None,
            "settled_frames": metadata.get("settled_frames") if metadata else None,
            "required_settle_frames": metadata.get("required_settle_frames")
            if metadata
            else None,
            "submitted_frames": self._submitted_frames,
            "processed_frames": self._processed_frames,
            "processed_fps": round(
                self._processed_frames / max(0.001, time.time() - self._started_at),
                2,
            ),
            "no_hand_streak": self._no_hand_streak,
            "hand_state": self._hand_state_label(hand_count, candidate),
        }

    @staticmethod
    def _hand_state_label(
        hand_count: int,
        candidate: GestureCandidate | None,
    ) -> str:
        if hand_count <= 0:
            return "no_hands"
        if candidate is None:
            return "hands_without_candidate"
        return "candidate"

    def _log_no_hands_if_needed(self) -> None:
        now = time.time()
        if self._no_hand_streak < max(1, int(GESTURE_TARGET_FPS * 2)):
            return
        if now - self._last_no_hand_log_at < 5.0:
            return
        self._last_no_hand_log_at = now
        logger.info(
            "GESTURE_DIAG | no_hands streak=%d processed=%d submitted=%d fps=%.2f",
            self._no_hand_streak,
            self._processed_frames,
            self._submitted_frames,
            self._processed_frames / max(0.001, now - self._started_at),
        )

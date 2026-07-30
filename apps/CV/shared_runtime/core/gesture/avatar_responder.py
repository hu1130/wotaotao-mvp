"""Idle-only avatar responses for stable gesture events."""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass

from config import (
    GESTURE_RESPONSE_GLOBAL_COOLDOWN_SECONDS,
    GESTURE_RESPONSE_PENDING_SECONDS,
)
from core.gesture.event_manager import STAGE_POLICIES
from core.gesture.schemas import GestureEvent
from core.voice_system import (
    TTSRequest,
    VoiceSystem,
    tts_priority_for_event,
    tts_priority_for_item,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GestureAvatarAction:
    event_type: str
    text: str
    cooldown_seconds: float
    expression: str = "Smile"


GESTURE_AVATAR_ACTIONS = {
    "wave": GestureAvatarAction(
        event_type="gesture_wave",
        text="你好呀，我看到你在招手。",
        cooldown_seconds=0.0,
        expression="Smile",
    ),
    "thumbs_up": GestureAvatarAction(
        event_type="gesture_thumbs_up",
        text="谢谢认可！",
        cooldown_seconds=0.0,
        expression="Smile",
    ),
    "heart": GestureAvatarAction(
        event_type="gesture_heart",
        text="哎呀，谢谢你的喜欢。",
        cooldown_seconds=0.0,
        expression="Blushing",
    ),
    "ok": GestureAvatarAction(
        event_type="gesture_ok",
        text="收到，没问题。",
        cooldown_seconds=0.0,
        expression="Smile",
    ),
    "peace": GestureAvatarAction(
        event_type="gesture_peace",
        text="耶，今天也很有精神！",
        cooldown_seconds=0.0,
        expression="Smile",
    ),
    "middle_finger": GestureAvatarAction(
        event_type="gesture_middle_finger",
        text="傻鸟吧，给我竖中指",
        cooldown_seconds=0.0,
        expression="Angry",
    ),
}


class GestureAvatarResponder:
    """Maps stable gesture events to low-priority avatar responses."""

    def __init__(self, voice_system: VoiceSystem, stage: str) -> None:
        self.voice_system = voice_system
        self.stage = stage
        self.policy = STAGE_POLICIES.get(stage, STAGE_POLICIES["observe"])
        self._lock = threading.Lock()
        self._gesture_cooldowns: dict[str, float] = {}
        self._global_ready_at = 0.0
        self._pending_until = 0.0

    def handle_event(self, event: GestureEvent) -> bool:
        if not self.policy.drives_avatar:
            return False

        now = time.time()
        self._gesture_cooldowns = {
            k: v for k, v in self._gesture_cooldowns.items() if v > now
        }

        action = GESTURE_AVATAR_ACTIONS.get(event.name)
        if action is None:
            return False

        with self._lock:
            if now < self._pending_until and self._is_legacy_audio_idle():
                self._pending_until = 0.0
            if now < self._global_ready_at:
                self._log_skip(event, "global_cooldown")
                return False
            if now < self._gesture_cooldowns.get(event.name, 0.0):
                self._log_skip(event, "gesture_cooldown")
                return False

            realtime_active = self._is_realtime_priority_active()
            if realtime_active:
                self._log_skip(event, "realtime_dialog_active")
                return False
            if self._has_same_or_higher_priority_audio(action.event_type):
                self._log_skip(event, "same_or_higher_priority_audio_busy")
                return False

            if not self._enqueue_visual_response(event, action):
                return False

            speech_enqueued = self._enqueue_speech_response(event, action, now)
            if GESTURE_RESPONSE_GLOBAL_COOLDOWN_SECONDS > 0:
                self._global_ready_at = now + GESTURE_RESPONSE_GLOBAL_COOLDOWN_SECONDS
            if action.cooldown_seconds > 0:
                self._gesture_cooldowns[event.name] = now + action.cooldown_seconds
            logger.info(
                "GESTURE_RESPONSE | %s | event=%s confidence=%.2f stage=%s speech=%s",
                action.event_type,
                event.name,
                event.confidence,
                self.policy.key,
                "queued" if speech_enqueued else "skipped",
            )
            return True

    def _is_realtime_priority_active(self) -> bool:
        realtime_priority_active = getattr(
            self.voice_system.speech_suppression,
            "is_set",
            None,
        )
        if callable(realtime_priority_active) and realtime_priority_active():
            return True
        return False

    def _is_legacy_audio_idle(self) -> bool:
        return not self.voice_system.is_legacy_audio_busy()

    def is_realtime_priority_active(self) -> bool:
        return self._is_realtime_priority_active()

    def _has_same_or_higher_priority_audio(self, event_type: str) -> bool:
        priority = tts_priority_for_event(event_type)
        return self.voice_system.has_legacy_audio_at_or_above_priority(priority)

    def _enqueue_visual_response(
        self,
        event: GestureEvent,
        action: GestureAvatarAction,
    ) -> bool:
        payload = {
            "gesture": event.name,
            "confidence": event.confidence,
            "hand": event.hand,
            "expression": action.expression,
        }
        try:
            self.voice_system.live2d.enqueue(action.event_type, payload)
            return True
        except queue.Full:
            self._log_skip(event, "queue_full")
            return False

    def _enqueue_speech_response(
        self,
        event: GestureEvent,
        action: GestureAvatarAction,
        now: float,
    ) -> bool:
        if now < self._pending_until:
            logger.debug(
                "Gesture speech skipped: gesture=%s reason=gesture_response_pending confidence=%.2f",
                event.name,
                event.confidence,
            )
            return False
        voice, model_key = self.voice_system.resolve_current_tts_voice()
        request = TTSRequest(
            event_type=action.event_type,
            text=action.text,
            name="访客",
            voice=voice,
        )
        try:
            enqueued = self.voice_system.enqueue_tts(request)
            if not enqueued:
                return False
            active_priority = self.voice_system.audio_player.active_priority()
            if active_priority is not None and active_priority < tts_priority_for_item(
                request
            ):
                logger.debug(
                    "Gesture speech queued behind higher priority audio: gesture=%s confidence=%.2f",
                    event.name,
                    event.confidence,
                )
            self._pending_until = now + GESTURE_RESPONSE_PENDING_SECONDS
            logger.debug(
                "Gesture speech voice resolved: gesture=%s model=%s voice=%s",
                event.name,
                model_key or "default",
                voice,
            )
            return True
        except queue.Full:
            self._log_skip(event, "tts_queue_full")
            return False

    def _log_skip(self, event: GestureEvent, reason: str) -> None:
        logger.debug(
            "Gesture response skipped: gesture=%s reason=%s confidence=%.2f",
            event.name,
            reason,
            event.confidence,
        )

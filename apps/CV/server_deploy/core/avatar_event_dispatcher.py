"""Centralized avatar action and fixed-speech dispatch for API-only recognition."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import threading
import time
import urllib.request
from dataclasses import dataclass

from config import (
    API_KEY,
    API_SECRET,
    AVATAR_FIXED_SPEECH_DEDUP_SECONDS,
    AVATAR_SERVER_URL,
)
from core.daily_tts_texts import choose_text
from core.tts_texts import TTS_TEXTS
from core.tenant import DEFAULT_TENANT_ID, normalize_tenant_id

logger = logging.getLogger("uvicorn.error")

ATTENDANCE_SPEECH_EVENTS = {"check_in", "check_out", "first_time", "returning"}
NAMED_SPEECH_EVENTS = ATTENDANCE_SPEECH_EVENTS | {"repeat"}
SPEECH_EVENTS = NAMED_SPEECH_EVENTS | {
    "stranger",
    "returning_stranger",
    "stranger_stare",
    "checked_in_stare",
    "idle_long",
    "crowd",
}
SILENT_ACTIONS = {"attention"}
EVENT_PRIORITIES = {
    "check_in": 85,
    "check_out": 85,
    "first_time": 82,
    "returning": 82,
    "repeat": 70,
    "stranger": 30,
    "returning_stranger": 30,
    "stranger_stare": 15,
    "checked_in_stare": 15,
    "idle_long": 10,
    "crowd": 10,
}


@dataclass(frozen=True)
class DispatchResult:
    action_sent: bool
    speech_sent: bool
    speech_type: str = ""
    reason: str = ""


class RemoteAvatarEventDispatcher:
    """Turns normalized recognition events into avatar actions and fixed speech.

    Remote recognition should emit business events only. This dispatcher owns the
    fixed speech decision: event type resolution, text selection, priority,
    short duplicate suppression, and debug logging.
    """

    def __init__(self, avatar_url: str = AVATAR_SERVER_URL):
        self.avatar_url = avatar_url.rstrip("/")
        self._lock = threading.RLock()
        self._last_speech_at: dict[str, float] = {}
        self._speech_suppressed_until: dict[str, float] = {}

    def emit(self, event_type: str, payload: dict) -> DispatchResult:
        event_type = (event_type or "").strip()
        if not event_type:
            return DispatchResult(False, False, reason="empty_event_type")

        action_payload = {"type": event_type, **(payload or {})}
        tenant_id = normalize_tenant_id(
            str(action_payload.get("tenant_id") or DEFAULT_TENANT_ID)
        )
        action_payload["tenant_id"] = tenant_id
        action_sent = self._post(action_payload)

        if event_type in SILENT_ACTIONS:
            return DispatchResult(action_sent, False, reason="silent_action")

        speech_type = self._resolve_speech_type(event_type, payload or {})
        if speech_type not in SPEECH_EVENTS:
            return DispatchResult(action_sent, False, speech_type, "not_speech_event")

        name = self._resolve_name(payload or {})
        speech = self._build_speech_payload(speech_type, name, tenant_id)
        if not speech:
            return DispatchResult(action_sent, False, speech_type, "no_text")

        now = time.time()
        suppressed_until = self._get_suppressed_until(speech_type, tenant_id)
        if now < suppressed_until:
            logger.info(
                "固定语音已抑制: type=%s name=%s remaining=%.1fs",
                speech_type,
                name,
                suppressed_until - now,
            )
            return DispatchResult(action_sent, False, speech_type, "suppressed")

        dedup_key = self._dedup_key(speech_type, name, tenant_id)
        dedup_seconds = max(0.0, AVATAR_FIXED_SPEECH_DEDUP_SECONDS)
        with self._lock:
            last_at = self._last_speech_at.get(dedup_key, 0.0)
            if dedup_seconds > 0 and now - last_at < dedup_seconds:
                logger.info(
                    "固定语音跳过去重: key=%s remaining=%.1fs",
                    dedup_key,
                    dedup_seconds - (now - last_at),
                )
                return DispatchResult(action_sent, False, speech_type, "dedup")
            self._last_speech_at[dedup_key] = now

        speech_sent = self._post(speech)
        logger.info(
            "固定语音调度完成: action=%s speech=%s type=%s name=%s priority=%s",
            event_type,
            speech_sent,
            speech_type,
            name,
            speech.get("priority"),
        )
        return DispatchResult(action_sent, speech_sent, speech_type)

    def emit_custom_speech(
        self,
        *,
        text: str,
        tenant_id: str = DEFAULT_TENANT_ID,
        event_type: str = "custom_speech",
        name: str = "",
        priority: int = 70,
        source: str = "custom_speech_dispatcher",
        dedup_key: str = "",
    ) -> DispatchResult:
        text = " ".join((text or "").split())[:240]
        event_type = (event_type or "custom_speech").strip()[:80]
        tenant_id = normalize_tenant_id(tenant_id)
        if not text:
            return DispatchResult(False, False, event_type, "empty_text")

        dedup_seconds = max(0.0, AVATAR_FIXED_SPEECH_DEDUP_SECONDS)
        dedup_key = dedup_key or self._dedup_key(event_type, text, tenant_id)
        now = time.time()
        with self._lock:
            last_at = self._last_speech_at.get(dedup_key, 0.0)
            if dedup_seconds > 0 and now - last_at < dedup_seconds:
                logger.info(
                    "动态语音跳过去重: key=%s remaining=%.1fs",
                    dedup_key,
                    dedup_seconds - (now - last_at),
                )
                return DispatchResult(False, False, event_type, "dedup")
            self._last_speech_at[dedup_key] = now

        speech = {
            "type": "speech",
            "event_type": event_type,
            "name": name,
            "tenant_id": tenant_id,
            "text": text,
            "priority": int(priority),
            "source": source,
            "visual_fallback": False,
        }
        speech_sent = self._post(speech)
        logger.info(
            "动态语音调度完成: speech=%s type=%s name=%s priority=%s chars=%d",
            speech_sent,
            event_type,
            name,
            priority,
            len(text),
        )
        return DispatchResult(False, speech_sent, event_type)

    def suppress_speech(
        self,
        event_type: str,
        seconds: float,
        reason: str = "",
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> None:
        tenant_id = normalize_tenant_id(tenant_id)
        speech_type = self._resolve_speech_type(event_type, {})
        seconds = max(0.0, seconds)
        if not speech_type or seconds <= 0:
            return
        until = time.time() + seconds
        with self._lock:
            suppression_key = f"{tenant_id}:{speech_type}"
            self._speech_suppressed_until[suppression_key] = max(
                self._speech_suppressed_until.get(suppression_key, 0.0),
                until,
            )
        logger.info(
            "固定语音抑制窗口已设置: type=%s seconds=%.1f reason=%s",
            speech_type,
            seconds,
            reason,
        )

    def _build_speech_payload(
        self, speech_type: str, name: str, tenant_id: str
    ) -> dict:
        text = self._pick_text(speech_type, name, tenant_id)
        if not text:
            return {}
        return {
            "type": "speech",
            "event_type": speech_type,
            "name": name,
            "tenant_id": tenant_id,
            "text": text,
            "priority": EVENT_PRIORITIES.get(speech_type, 10),
            "source": "fixed_speech_dispatcher",
            "visual_fallback": False,
        }

    def _pick_text(self, event_type: str, name: str, tenant_id: str) -> str:
        require_name = event_type in NAMED_SPEECH_EVENTS
        text = choose_text(
            TTS_TEXTS,
            event_type,
            require_placeholder=require_name,
            tenant_id=tenant_id,
        )
        if not text and require_name:
            text = self._fallback_named_text(event_type)
        if not text:
            text = choose_text(TTS_TEXTS, event_type, tenant_id=tenant_id)
        if not text:
            return ""
        if "{}" in text:
            return text.format(name or "访客")
        return text

    @staticmethod
    def _fallback_named_text(event_type: str) -> str:
        if event_type == "stranger":
            return "{}，欢迎来到这里～"
        if event_type == "returning_stranger":
            return "{}，又见面啦，欢迎回来。"
        return ""

    @staticmethod
    def _resolve_speech_type(event_type: str, payload: dict) -> str:
        if event_type == "stranger" and payload.get("is_returning"):
            return "returning_stranger"
        return event_type

    @staticmethod
    def _resolve_name(payload: dict) -> str:
        return (
            payload.get("name")
            or payload.get("salutation")
            or payload.get("visitor_label")
            or "访客"
        )

    @staticmethod
    def _dedup_key(speech_type: str, name: str, tenant_id: str) -> str:
        return f"{tenant_id}:{speech_type}:{name or '访客'}"

    def _get_suppressed_until(self, speech_type: str, tenant_id: str) -> float:
        with self._lock:
            return self._speech_suppressed_until.get(f"{tenant_id}:{speech_type}", 0.0)

    def _post(self, payload: dict) -> bool:
        try:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            path = "/event"
            timestamp = str(int(time.time()))
            signing_payload = f"POST\n{path}\n{timestamp}\n".encode("utf-8") + data
            signature = hmac.new(
                API_SECRET.encode("utf-8"), signing_payload, hashlib.sha256
            ).hexdigest()
            req = urllib.request.Request(
                f"{self.avatar_url}{path}",
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "X-Api-Key": API_KEY,
                    "X-Timestamp": timestamp,
                    "X-Signature": signature,
                },
                method="POST",
            )
            urllib.request.urlopen(req, timeout=0.5).close()
            logger.info(
                "avatar 事件已发送: url=%s/event type=%s event_type=%s",
                self.avatar_url,
                payload.get("type"),
                payload.get("event_type", ""),
            )
            return True
        except Exception as exc:
            logger.warning(
                "avatar 事件发送失败: url=%s/event type=%s event_type=%s error=%s",
                self.avatar_url,
                payload.get("type"),
                payload.get("event_type", ""),
                exc,
            )
            return False

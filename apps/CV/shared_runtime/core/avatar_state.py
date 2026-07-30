"""Shared cached reads for avatar server state."""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from api.auth import sign_request
from config import API_BASE_URL, API_KEY, API_SECRET, AVATAR_SERVER_URL


@dataclass(frozen=True)
class AvatarReadyState:
    ready: bool = False
    model: str = ""
    raw: dict[str, Any] | None = None


@dataclass(frozen=True)
class AudioLockState:
    active: bool = False
    owner: str = ""
    owners: tuple[str, ...] = ()


class AvatarStateCache:
    """Short-lived cache for high-frequency avatar HTTP status endpoints."""

    def __init__(self, base_url: str = AVATAR_SERVER_URL):
        self.base_url = base_url.rstrip("/")
        self._lock = threading.Lock()
        self._ready_cached_until = 0.0
        self._ready_state = AvatarReadyState()
        self._audio_lock_cached_until = 0.0
        self._audio_lock_state = AudioLockState()
        self._session_token = ""
        self._session_expires_at = 0.0
        self._session_lock = threading.Lock()

    def get_ready_state(
        self,
        ttl_seconds: float = 1.0,
        timeout_seconds: float = 0.2,
    ) -> AvatarReadyState:
        now = time.time()
        with self._lock:
            if now < self._ready_cached_until:
                return self._ready_state

        state = self._fetch_ready_state(timeout_seconds)
        with self._lock:
            self._ready_state = state
            self._ready_cached_until = time.time() + ttl_seconds
            return self._ready_state

    def is_dialog_audio_locked(
        self,
        ttl_seconds: float = 0.25,
        timeout_seconds: float = 0.15,
    ) -> bool:
        return self.get_audio_lock_state(ttl_seconds, timeout_seconds).active

    def is_external_audio_locked(
        self,
        ttl_seconds: float = 0.25,
        timeout_seconds: float = 0.15,
    ) -> bool:
        state = self.get_audio_lock_state(ttl_seconds, timeout_seconds)
        if not state.active:
            return False
        owners = state.owners or ((state.owner,) if state.owner else ())
        return any(owner and owner != "legacy_tts" for owner in owners)

    def get_audio_lock_state(
        self,
        ttl_seconds: float = 0.25,
        timeout_seconds: float = 0.15,
    ) -> AudioLockState:
        now = time.time()
        with self._lock:
            if now < self._audio_lock_cached_until:
                return self._audio_lock_state

        state = self._fetch_dialog_audio_lock(timeout_seconds)
        with self._lock:
            self._audio_lock_state = state
            self._audio_lock_cached_until = time.time() + ttl_seconds
            return self._audio_lock_state

    def invalidate(self) -> None:
        with self._lock:
            self._ready_cached_until = 0.0
            self._audio_lock_cached_until = 0.0

    def set_audio_lock(
        self,
        active: bool,
        *,
        hold_ms: int,
        owner: str,
        timeout_seconds: float = 0.2,
    ) -> None:
        self._request_json(
            "POST",
            "/dialog-audio-lock",
            {"active": bool(active), "holdMs": int(hold_ms), "owner": owner},
            timeout_seconds,
        )
        self.invalidate()

    def _fetch_ready_state(self, timeout_seconds: float) -> AvatarReadyState:
        try:
            data = self._get_json("/avatar-ready", timeout_seconds)
            return AvatarReadyState(
                ready=bool(data.get("ready")),
                model=str(data.get("model") or ""),
                raw=data,
            )
        except Exception:
            return AvatarReadyState()

    def _fetch_dialog_audio_lock(self, timeout_seconds: float) -> AudioLockState:
        try:
            data = self._get_json("/dialog-audio-lock", timeout_seconds)
            owners = data.get("owners")
            if not isinstance(owners, list):
                owners = []
            return AudioLockState(
                active=bool(data.get("active")),
                owner=str(data.get("owner") or ""),
                owners=tuple(str(owner) for owner in owners if owner),
            )
        except Exception:
            return AudioLockState()

    def _get_json(self, path: str, timeout_seconds: float) -> dict[str, Any]:
        return self._request_json("GET", path, None, timeout_seconds)

    def _request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        body = (
            b""
            if payload is None
            else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        )
        for attempt in range(2):
            headers, used_session = self._authentication_headers(
                method, path, body, force_refresh=attempt > 0
            )
            if body:
                headers["Content-Type"] = "application/json"
            request = urllib.request.Request(
                f"{self.base_url}{path}",
                data=body if body else None,
                headers=headers,
                method=method,
            )
            try:
                with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                    data = json.loads(response.read().decode("utf-8"))
                return data if isinstance(data, dict) else {}
            except urllib.error.HTTPError as exc:
                if exc.code == 401 and used_session and attempt == 0:
                    self._clear_session()
                    continue
                raise
        return {}

    def _authentication_headers(
        self,
        method: str,
        path: str,
        body: bytes,
        *,
        force_refresh: bool,
    ) -> tuple[dict[str, str], bool]:
        session_token = self._device_session_token(force_refresh=force_refresh)
        if session_token:
            return {"X-Avatar-Session": session_token}, True
        if not API_KEY or not API_SECRET:
            raise RuntimeError("avatar state authentication is unavailable")
        timestamp = str(int(time.time()))
        return (
            {
                "X-Api-Key": API_KEY,
                "X-Timestamp": timestamp,
                "X-Signature": sign_request(
                    API_SECRET,
                    method,
                    path,
                    timestamp,
                    body,
                ),
            },
            False,
        )

    def _device_session_token(self, *, force_refresh: bool = False) -> str:
        try:
            from core.device_identity import get_enrolled_device_identity
        except ImportError:
            return ""

        identity = get_enrolled_device_identity(API_BASE_URL)
        if identity is None:
            return ""
        now = time.time()
        with self._session_lock:
            if (
                not force_refresh
                and self._session_token
                and self._session_expires_at > now + 30
            ):
                return self._session_token
            from core.api_client import SignedApiClient

            response = SignedApiClient(base_url=API_BASE_URL).post(
                "/api/v1/device-sessions/avatar-state-session",
                {},
                timeout=max(1.0, 0.2),
            )
            data = response.get("data") if isinstance(response, dict) else None
            if not isinstance(data, dict):
                raise RuntimeError("avatar state session response is invalid")
            token = str(data.get("sessionToken") or "")
            expires_at = float(data.get("expiresAt") or 0.0)
            if not token or expires_at <= now:
                raise RuntimeError("avatar state session is missing or expired")
            self._session_token = token
            self._session_expires_at = expires_at
            return token

    def _clear_session(self) -> None:
        with self._session_lock:
            self._session_token = ""
            self._session_expires_at = 0.0


_DEFAULT_CACHE = AvatarStateCache()


def get_avatar_state_cache() -> AvatarStateCache:
    return _DEFAULT_CACHE

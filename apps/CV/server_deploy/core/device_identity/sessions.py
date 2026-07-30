"""One-time browser bootstrap tickets and tenant-bound avatar sessions."""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import threading
import time

from config import AVATAR_BOOTSTRAP_TTL_SECONDS, AVATAR_SESSION_TTL_SECONDS
from core.redis_health import RedisHealthMonitor
from core.tenant import normalize_tenant_id

from .models import AvatarSessionBinding
from .service import (
    DeviceAuthenticationUnavailable,
    DeviceAuthenticationService,
    get_device_authentication_service,
)


logger = logging.getLogger(__name__)


class DeviceSessionStore:
    def __init__(
        self,
        health: RedisHealthMonitor | None = None,
        device_auth: DeviceAuthenticationService | None = None,
    ) -> None:
        self._health = health or RedisHealthMonitor(name="设备浏览器会话")
        if health is None:
            self._health.initialize()
        self._device_auth = device_auth or get_device_authentication_service()

    def issue_bootstrap(self, tenant_id: str, device_id: str) -> tuple[str, float]:
        device = self._device_auth.get_active_device(device_id)
        tenant_id = normalize_tenant_id(tenant_id)
        if device is None or device.tenant_id != tenant_id:
            raise ValueError("device is not active in tenant")
        ttl = max(15, int(AVATAR_BOOTSTRAP_TTL_SECONDS))
        token = secrets.token_urlsafe(32)
        expires_at = time.time() + ttl
        self._set_json(
            self._bootstrap_key(token),
            {"tenant_id": tenant_id, "device_id": device_id, "expires_at": expires_at},
            ttl,
        )
        logger.info(
            "数字人启动票据已签发: tenant=%s device=%s ttl=%ds",
            tenant_id,
            device_id,
            ttl,
        )
        return token, expires_at

    def consume_bootstrap(self, token: str) -> tuple[str, AvatarSessionBinding] | None:
        payload = self._consume_json(self._bootstrap_key(token))
        if payload is None:
            return None
        tenant_id = normalize_tenant_id(str(payload.get("tenant_id") or ""))
        device_id = str(payload.get("device_id") or "")
        device = self._device_auth.get_active_device(device_id)
        if device is None or device.tenant_id != tenant_id:
            return None
        return self.issue_session(tenant_id, device_id)

    def issue_session(
        self, tenant_id: str, device_id: str
    ) -> tuple[str, AvatarSessionBinding]:
        """Issue an avatar session directly to an authenticated active device."""

        device = self._device_auth.get_active_device(device_id)
        tenant_id = normalize_tenant_id(tenant_id)
        if device is None or device.tenant_id != tenant_id:
            raise ValueError("device is not active in tenant")
        ttl = max(300, int(AVATAR_SESSION_TTL_SECONDS))
        session_token = secrets.token_urlsafe(40)
        binding = AvatarSessionBinding(
            tenant_id=tenant_id,
            device_id=device_id,
            expires_at=time.time() + ttl,
        )
        self._set_json(
            self._session_key(session_token),
            {
                "tenant_id": binding.tenant_id,
                "device_id": binding.device_id,
                "expires_at": binding.expires_at,
            },
            ttl,
        )
        logger.info(
            "数字人租户会话已建立: tenant=%s device=%s ttl=%ds",
            tenant_id,
            device_id,
            ttl,
        )
        return session_token, binding

    def authenticate_session(self, token: str) -> AvatarSessionBinding | None:
        token = (token or "").strip()
        if not token or len(token) > 256:
            return None
        client = self._client()
        key = self._session_key(token)
        try:
            raw = client.get(key)
            if not raw:
                return None
            payload = json.loads(raw)
            tenant_id = normalize_tenant_id(str(payload.get("tenant_id") or ""))
            device_id = str(payload.get("device_id") or "")
            device = self._device_auth.get_active_device(device_id)
            if device is None or device.tenant_id != tenant_id:
                client.delete(key)
                return None
            ttl = max(300, int(AVATAR_SESSION_TTL_SECONDS))
            expires_at = time.time() + ttl
            client.setex(
                key,
                ttl,
                json.dumps(
                    {
                        "tenant_id": tenant_id,
                        "device_id": device_id,
                        "expires_at": expires_at,
                    },
                    separators=(",", ":"),
                ),
            )
            return AvatarSessionBinding(tenant_id, device_id, expires_at)
        except DeviceAuthenticationUnavailable:
            raise
        except Exception as exc:
            self._health.mark_unhealthy()
            raise DeviceAuthenticationUnavailable("数字人会话存储异常") from exc

    def _set_json(self, key: str, payload: dict[str, object], ttl: int) -> None:
        try:
            self._client().setex(
                key, ttl, json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            )
        except DeviceAuthenticationUnavailable:
            raise
        except Exception as exc:
            self._health.mark_unhealthy()
            raise DeviceAuthenticationUnavailable("设备会话存储异常") from exc

    def _consume_json(self, key: str) -> dict[str, object] | None:
        try:
            raw = self._client().eval(
                "local v=redis.call('GET',KEYS[1]); "
                "if v then redis.call('DEL',KEYS[1]); end; return v",
                1,
                key,
            )
            return json.loads(raw) if raw else None
        except DeviceAuthenticationUnavailable:
            raise
        except Exception as exc:
            self._health.mark_unhealthy()
            raise DeviceAuthenticationUnavailable("设备会话存储异常") from exc

    def _client(self):
        if not self._health.ensure_connected():
            raise DeviceAuthenticationUnavailable("设备会话存储不可用")
        return self._health.client

    @classmethod
    def _bootstrap_key(cls, token: str) -> str:
        return f"device_avatar_bootstrap:{cls._token_hash(token)}"

    @classmethod
    def _session_key(cls, token: str) -> str:
        return f"device_avatar_session:{cls._token_hash(token)}"

    @staticmethod
    def _token_hash(token: str) -> str:
        value = (token or "").strip()
        if not value or len(value) > 256:
            return "invalid"
        return hashlib.sha256(value.encode("utf-8")).hexdigest()


_store: DeviceSessionStore | None = None
_store_lock = threading.Lock()


def get_device_session_store() -> DeviceSessionStore:
    global _store
    if _store is not None:
        return _store
    with _store_lock:
        if _store is None:
            _store = DeviceSessionStore()
        return _store

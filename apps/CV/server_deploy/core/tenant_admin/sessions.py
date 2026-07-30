"""Redis-backed tenant administrator sessions shared by API and avatar."""

from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time

from config import TENANT_ADMIN_SESSION_TTL_SECONDS
from core.device_identity.service import DeviceAuthenticationUnavailable
from core.redis_health import RedisHealthMonitor

from .models import TenantAdminAccount, TenantAdminSessionBinding
from .repository import TenantAdminRepository


class TenantAdminSessionStore:
    def __init__(
        self,
        health: RedisHealthMonitor | None = None,
        repository: TenantAdminRepository | None = None,
    ) -> None:
        self._health = health or RedisHealthMonitor(name="租户管理员会话")
        if health is None:
            self._health.initialize()
        self._repository = repository or TenantAdminRepository()

    def issue(self, account: TenantAdminAccount) -> tuple[str, TenantAdminSessionBinding]:
        if not account.active:
            raise ValueError("tenant administrator is disabled")
        ttl = max(300, int(TENANT_ADMIN_SESSION_TTL_SECONDS))
        token = secrets.token_urlsafe(40)
        binding = TenantAdminSessionBinding(
            account_id=account.account_id,
            tenant_id=account.tenant_id,
            tenant_name=account.tenant_name,
            username=account.username,
            display_name=account.display_name,
            auth_version=account.auth_version,
            expires_at=time.time() + ttl,
        )
        self._write(token, binding, ttl)
        return token, binding

    def authenticate(self, token: str) -> TenantAdminSessionBinding | None:
        token = (token or "").strip()
        if not token or len(token) > 256:
            return None
        client = self._client()
        key = self._key(token)
        try:
            raw = client.get(key)
            if not raw:
                return None
            payload = json.loads(raw)
            account = self._repository.get_account_by_id(int(payload["account_id"]))
            if account is None or not account.active:
                client.delete(key)
                return None
            if (
                account.tenant_id != str(payload.get("tenant_id") or "")
                or account.username != str(payload.get("username") or "")
                or account.auth_version != int(payload.get("auth_version") or 0)
            ):
                client.delete(key)
                return None
            ttl = max(300, int(TENANT_ADMIN_SESSION_TTL_SECONDS))
            binding = TenantAdminSessionBinding(
                account_id=account.account_id,
                tenant_id=account.tenant_id,
                tenant_name=account.tenant_name,
                username=account.username,
                display_name=account.display_name,
                auth_version=account.auth_version,
                expires_at=time.time() + ttl,
            )
            self._write(token, binding, ttl)
            return binding
        except DeviceAuthenticationUnavailable:
            raise
        except Exception as exc:
            self._health.mark_unhealthy()
            raise DeviceAuthenticationUnavailable("租户管理员会话存储异常") from exc

    def revoke(self, token: str) -> None:
        try:
            self._client().delete(self._key(token))
        except DeviceAuthenticationUnavailable:
            raise
        except Exception as exc:
            self._health.mark_unhealthy()
            raise DeviceAuthenticationUnavailable("租户管理员会话撤销失败") from exc

    def _write(
        self, token: str, binding: TenantAdminSessionBinding, ttl: int
    ) -> None:
        try:
            self._client().setex(
                self._key(token),
                ttl,
                json.dumps(
                    {
                        "account_id": binding.account_id,
                        "tenant_id": binding.tenant_id,
                        "tenant_name": binding.tenant_name,
                        "username": binding.username,
                        "display_name": binding.display_name,
                        "auth_version": binding.auth_version,
                        "expires_at": binding.expires_at,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )
        except DeviceAuthenticationUnavailable:
            raise
        except Exception as exc:
            self._health.mark_unhealthy()
            raise DeviceAuthenticationUnavailable("租户管理员会话存储异常") from exc

    def _client(self):
        if not self._health.ensure_connected():
            raise DeviceAuthenticationUnavailable("租户管理员会话存储不可用")
        return self._health.client

    @staticmethod
    def _key(token: str) -> str:
        digest = hashlib.sha256((token or "").encode("utf-8")).hexdigest()
        return f"tenant_admin_session:{digest}"


_store: TenantAdminSessionStore | None = None
_store_lock = threading.Lock()


def get_tenant_admin_session_store() -> TenantAdminSessionStore:
    global _store
    if _store is not None:
        return _store
    with _store_lock:
        if _store is None:
            _store = TenantAdminSessionStore()
        return _store

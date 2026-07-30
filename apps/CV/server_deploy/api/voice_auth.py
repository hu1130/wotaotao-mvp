"""Short-lived, one-time tenant tickets for browser voice WebSockets."""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import threading
import time
from dataclasses import dataclass

from config import VOICE_TICKET_TTL_SECONDS
from core.redis_health import RedisHealthMonitor
from core.tenant import normalize_tenant_id

logger = logging.getLogger("uvicorn.error")


@dataclass(frozen=True, slots=True)
class VoiceTicketBinding:
    tenant_id: str
    device_id: str
    expires_at: float


class VoiceTicketStore:
    """Issues opaque tickets and atomically consumes them through Redis."""

    def __init__(self, health: RedisHealthMonitor | None = None) -> None:
        self._health = health or RedisHealthMonitor(name="语音票据")
        if health is None:
            self._health.initialize()
        self._lock = threading.RLock()
        self._local: dict[str, VoiceTicketBinding] = {}

    def issue(self, tenant_id: str, device_id: str) -> tuple[str, VoiceTicketBinding]:
        tenant_id = normalize_tenant_id(tenant_id)
        device_id = (device_id or "").strip()[:80]
        if not device_id:
            raise ValueError("device_id is required")
        ttl = max(10, int(VOICE_TICKET_TTL_SECONDS))
        token = secrets.token_urlsafe(32)
        token_hash = self._token_hash(token)
        binding = VoiceTicketBinding(
            tenant_id=tenant_id,
            device_id=device_id,
            expires_at=time.time() + ttl,
        )
        with self._lock:
            self._prune_local_locked()
            self._local[token_hash] = binding
        if self._health.ensure_connected():
            try:
                self._health.client.setex(
                    self._redis_key(token_hash),
                    ttl,
                    json.dumps(
                        {
                            "tenant_id": tenant_id,
                            "device_id": device_id,
                            "expires_at": binding.expires_at,
                        },
                        separators=(",", ":"),
                    ),
                )
            except Exception as exc:
                logger.warning("语音票据写入 Redis 失败，使用进程内票据: %s", exc)
                self._health.mark_unhealthy()
        logger.info(
            "语音票据已签发: tenant=%s device=%s ttl=%ds",
            tenant_id,
            device_id,
            ttl,
        )
        return token, binding

    def consume(self, token: str, device_id: str) -> VoiceTicketBinding | None:
        token_hash = self._token_hash(token)
        if not token_hash:
            return None
        device_id = (device_id or "").strip()[:80]
        redis_authoritative, redis_binding = self._consume_redis(token_hash)
        with self._lock:
            local_binding = self._local.pop(token_hash, None)
        binding = redis_binding if redis_authoritative else local_binding
        if binding is None or binding.expires_at < time.time():
            return None
        if not secrets.compare_digest(binding.device_id, device_id):
            logger.warning(
                "语音票据设备绑定不匹配: tenant=%s expected=%s actual=%s",
                binding.tenant_id,
                binding.device_id,
                device_id or "(empty)",
            )
            return None
        logger.info(
            "语音票据已消费: tenant=%s device=%s",
            binding.tenant_id,
            binding.device_id,
        )
        return binding

    def _consume_redis(
        self, token_hash: str
    ) -> tuple[bool, VoiceTicketBinding | None]:
        if not self._health.ensure_connected():
            return False, None
        try:
            value = self._health.client.eval(
                "local v=redis.call('GET',KEYS[1]); "
                "if v then redis.call('DEL',KEYS[1]); end; return v",
                1,
                self._redis_key(token_hash),
            )
            if not value:
                return True, None
            payload = json.loads(value)
            return True, VoiceTicketBinding(
                tenant_id=normalize_tenant_id(
                    str(payload.get("tenant_id") or "")
                ),
                device_id=str(payload.get("device_id") or "")[:80],
                expires_at=float(payload.get("expires_at") or 0.0),
            )
        except Exception as exc:
            logger.warning("语音票据消费 Redis 失败，尝试进程内票据: %s", exc)
            self._health.mark_unhealthy()
            return False, None

    def _prune_local_locked(self) -> None:
        now = time.time()
        expired = [key for key, value in self._local.items() if value.expires_at < now]
        for key in expired:
            self._local.pop(key, None)
        if len(self._local) > 2048:
            oldest = sorted(self._local, key=lambda key: self._local[key].expires_at)
            for key in oldest[: len(self._local) - 2048]:
                self._local.pop(key, None)

    @staticmethod
    def _token_hash(token: str) -> str:
        token = (token or "").strip()
        if not token or len(token) > 256:
            return ""
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _redis_key(token_hash: str) -> str:
        return f"voice_ticket:{token_hash}"


_store: VoiceTicketStore | None = None
_store_lock = threading.Lock()


def get_voice_ticket_store() -> VoiceTicketStore:
    global _store
    if _store is not None:
        return _store
    with _store_lock:
        if _store is None:
            _store = VoiceTicketStore()
        return _store

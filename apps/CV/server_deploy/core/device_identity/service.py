"""Enrollment validation and cached Ed25519 device authentication."""

from __future__ import annotations

import hashlib
import logging
import threading
import time
import uuid
from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from config import (
    API_SIGNATURE_TOLERANCE_SECONDS,
    DEVICE_AUTH_CACHE_TTL_SECONDS,
    DEVICE_AUTH_NONCE_TTL_SECONDS,
    DEVICE_LAST_SEEN_UPDATE_SECONDS,
)
from core.device_auth_protocol import (
    build_enrollment_proof_payload,
    build_device_signature_payload,
    decode_base64url,
    is_valid_device_id,
    is_valid_nonce,
)
from core.redis_health import RedisHealthMonitor

from .models import DeviceEnrollmentError, DeviceRecord, EnrollmentResult
from .repository import DeviceIdentityRepository


logger = logging.getLogger(__name__)


class DeviceAuthenticationUnavailable(RuntimeError):
    pass


class RedisNonceReplayGuard:
    """Redis-backed replay rejection; device auth fails closed when unavailable."""

    def __init__(self, health: RedisHealthMonitor | None = None) -> None:
        self._health = health or RedisHealthMonitor(name="设备签名防重放")
        if health is None:
            self._health.initialize()

    def accept(self, device_id: str, nonce: str) -> bool:
        if not self._health.ensure_connected():
            raise DeviceAuthenticationUnavailable("设备认证防重放存储不可用")
        digest = hashlib.sha256(f"{device_id}\0{nonce}".encode("utf-8")).hexdigest()
        try:
            return bool(
                self._health.client.set(
                    f"device_auth_nonce:{digest}",
                    "1",
                    ex=max(60, int(DEVICE_AUTH_NONCE_TTL_SECONDS)),
                    nx=True,
                )
            )
        except Exception as exc:
            self._health.mark_unhealthy()
            raise DeviceAuthenticationUnavailable("设备认证防重放存储异常") from exc


@dataclass(slots=True)
class _CachedDevice:
    record: DeviceRecord
    expires_at: float


class DeviceAuthenticationService:
    def __init__(
        self,
        repository: DeviceIdentityRepository | None = None,
        replay_guard: RedisNonceReplayGuard | None = None,
    ) -> None:
        self.repository = repository or DeviceIdentityRepository()
        self.replay_guard = replay_guard or RedisNonceReplayGuard()
        self._cache: dict[str, _CachedDevice] = {}
        self._cache_lock = threading.Lock()
        self._last_touch_at: dict[str, float] = {}
        self._touch_lock = threading.Lock()

    def enroll(
        self,
        *,
        activation_code: str,
        installation_id: str,
        public_key_b64: str,
        proof_signature_b64: str,
        display_name: str,
        platform_info: dict[str, object] | None,
    ) -> EnrollmentResult:
        activation_code = (activation_code or "").strip()
        if not 20 <= len(activation_code) <= 128:
            raise DeviceEnrollmentError(
                "activation_invalid", "激活码格式无效", status_code=401
            )
        try:
            canonical_installation_id = str(uuid.UUID((installation_id or "").strip()))
        except (ValueError, AttributeError) as exc:
            raise DeviceEnrollmentError(
                "installation_id_invalid", "installation_id 格式无效"
            ) from exc
        try:
            public_key = decode_base64url(public_key_b64, expected_length=32)
            public_key_object = Ed25519PublicKey.from_public_bytes(public_key)
            proof_signature = decode_base64url(proof_signature_b64, expected_length=64)
        except (ValueError, TypeError) as exc:
            raise DeviceEnrollmentError(
                "public_key_invalid", "Ed25519 公钥格式无效"
            ) from exc
        try:
            public_key_object.verify(
                proof_signature,
                build_enrollment_proof_payload(
                    activation_code,
                    canonical_installation_id,
                    public_key_b64,
                ),
            )
        except InvalidSignature as exc:
            raise DeviceEnrollmentError(
                "enrollment_proof_invalid",
                "设备未能证明 Ed25519 私钥持有权",
                status_code=401,
            ) from exc
        return self.repository.claim_activation_code(
            activation_code=activation_code,
            installation_id=canonical_installation_id,
            public_key=public_key,
            display_name=display_name,
            platform_info=platform_info,
        )

    def authenticate(
        self,
        *,
        method: str,
        path: str,
        timestamp: str | None,
        nonce: str | None,
        device_id: str | None,
        signature: str | None,
        body: bytes,
        tolerance_seconds: int = API_SIGNATURE_TOLERANCE_SECONDS,
    ) -> DeviceRecord | None:
        device_id = (device_id or "").strip()
        timestamp = (timestamp or "").strip()
        nonce = (nonce or "").strip()
        if not is_valid_device_id(device_id) or not is_valid_nonce(nonce):
            return None
        if not self._valid_timestamp(timestamp, tolerance_seconds):
            return None
        try:
            signature_bytes = decode_base64url(signature or "", expected_length=64)
        except ValueError:
            return None
        device = self.get_active_device(device_id)
        if device is None:
            return None
        payload = build_device_signature_payload(method, path, timestamp, nonce, body)
        try:
            Ed25519PublicKey.from_public_bytes(device.public_key).verify(
                signature_bytes, payload
            )
        except (InvalidSignature, ValueError):
            logger.warning("设备签名验证失败: device=%s path=%s", device_id, path)
            return None
        if not self.replay_guard.accept(device_id, nonce):
            logger.warning("设备签名重放已拒绝: device=%s path=%s", device_id, path)
            return None
        self._touch_device_if_due(device_id)
        logger.debug(
            "设备签名验证通过: tenant=%s device=%s method=%s path=%s",
            device.tenant_id,
            device.device_id,
            method,
            path,
        )
        return device

    def get_active_device(self, device_id: str) -> DeviceRecord | None:
        now = time.monotonic()
        with self._cache_lock:
            cached = self._cache.get(device_id)
            if cached and cached.expires_at > now:
                return cached.record if cached.record.active else None
        record = self.repository.get_device(device_id)
        if record is None:
            return None
        with self._cache_lock:
            self._cache[device_id] = _CachedDevice(
                record=record,
                expires_at=now + max(1, int(DEVICE_AUTH_CACHE_TTL_SECONDS)),
            )
            if len(self._cache) > 10000:
                expired = [
                    key for key, value in self._cache.items() if value.expires_at <= now
                ]
                for key in expired:
                    self._cache.pop(key, None)
        return record if record.active else None

    def invalidate(self, device_id: str) -> None:
        with self._cache_lock:
            self._cache.pop(device_id, None)
        with self._touch_lock:
            self._last_touch_at.pop(device_id, None)

    def _touch_device_if_due(self, device_id: str) -> None:
        now = time.monotonic()
        interval = max(1, int(DEVICE_LAST_SEEN_UPDATE_SECONDS))
        with self._touch_lock:
            if now - self._last_touch_at.get(device_id, 0.0) < interval:
                return
            self._last_touch_at[device_id] = now
        try:
            self.repository.touch_device(device_id, interval)
        except Exception as exc:
            with self._touch_lock:
                if self._last_touch_at.get(device_id) == now:
                    self._last_touch_at.pop(device_id, None)
            logger.warning("设备在线时间更新失败: device=%s error=%s", device_id, exc)

    @staticmethod
    def _valid_timestamp(value: str, tolerance_seconds: int) -> bool:
        try:
            timestamp = int(value)
        except (TypeError, ValueError):
            return False
        return abs(int(time.time()) - timestamp) <= max(1, tolerance_seconds)


_service: DeviceAuthenticationService | None = None
_service_lock = threading.Lock()


def get_device_authentication_service() -> DeviceAuthenticationService:
    global _service
    if _service is not None:
        return _service
    with _service_lock:
        if _service is None:
            _service = DeviceAuthenticationService()
        return _service

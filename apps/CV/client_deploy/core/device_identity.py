"""Persistent Ed25519 device identity with Windows DPAPI protection."""

from __future__ import annotations

import ctypes
import json
import logging
import os
import secrets
import threading
import time
import uuid
from ctypes import wintypes
from dataclasses import dataclass, replace
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)

from core.device_auth_protocol import (
    build_device_signature_payload,
    decode_base64url,
    encode_base64url,
    is_valid_device_id,
)
from core.tenant import normalize_tenant_id


logger = logging.getLogger(__name__)
_DPAPI_ENTROPY = b"CVClient/device-identity/v1"


@dataclass(frozen=True, slots=True)
class DeviceIdentity:
    installation_id: str
    private_key: Ed25519PrivateKey
    tenant_id: str = ""
    device_id: str = ""
    server_base_url: str = ""
    device_name: str = ""
    enrolled_at: float = 0.0

    @property
    def enrolled(self) -> bool:
        return bool(
            self.tenant_id
            and is_valid_device_id(self.device_id)
            and self.server_base_url
        )

    @property
    def public_key_bytes(self) -> bytes:
        return self.private_key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )

    @property
    def public_key_base64(self) -> str:
        return encode_base64url(self.public_key_bytes)

    def signed_headers(self, method: str, path: str, body: bytes) -> dict[str, str]:
        if not self.enrolled:
            raise RuntimeError("device identity is not enrolled")
        timestamp = str(int(time.time()))
        nonce = secrets.token_urlsafe(24)
        payload = build_device_signature_payload(method, path, timestamp, nonce, body)
        signature = self.private_key.sign(payload)
        return {
            "X-Device-Id": self.device_id,
            "X-Device-Timestamp": timestamp,
            "X-Device-Nonce": nonce,
            "X-Device-Signature": encode_base64url(signature),
        }


class DeviceIdentityStore:
    def __init__(self, path: str | os.PathLike | None = None) -> None:
        self.path = Path(path) if path else self.default_path()
        self._lock = threading.RLock()

    @staticmethod
    def default_path() -> Path:
        configured = os.environ.get("CLIENT_DEVICE_IDENTITY_PATH", "").strip()
        if configured:
            return Path(configured).expanduser().resolve()
        local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
        base = Path(local_app_data) if local_app_data else Path.home() / ".cvclient"
        return base / "CVClient" / "device-identity.json"

    def load(self) -> DeviceIdentity | None:
        with self._lock:
            if not self.path.exists():
                return None
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
                private_key_raw = self._unprotect_private_key(payload)
                private_key = Ed25519PrivateKey.from_private_bytes(private_key_raw)
                identity = DeviceIdentity(
                    installation_id=str(uuid.UUID(str(payload["installationId"]))),
                    private_key=private_key,
                    tenant_id=str(payload.get("tenantId") or ""),
                    device_id=str(payload.get("deviceId") or ""),
                    server_base_url=str(payload.get("serverBaseUrl") or "").rstrip("/"),
                    device_name=str(payload.get("deviceName") or ""),
                    enrolled_at=float(payload.get("enrolledAt") or 0.0),
                )
                stored_public_key = decode_base64url(
                    str(payload.get("publicKey") or ""), expected_length=32
                )
                if not secrets.compare_digest(
                    identity.public_key_bytes, stored_public_key
                ):
                    raise ValueError("public key does not match private key")
                if identity.tenant_id:
                    normalized = normalize_tenant_id(identity.tenant_id)
                    identity = replace(identity, tenant_id=normalized)
                return identity
            except Exception as exc:
                raise RuntimeError(
                    f"设备身份文件损坏或无法解密: {self.path}: {exc}"
                ) from exc

    def load_or_create_pending(self, device_name: str = "") -> DeviceIdentity:
        identity = self.load()
        if identity is not None:
            return identity
        identity = DeviceIdentity(
            installation_id=str(uuid.uuid4()),
            private_key=Ed25519PrivateKey.generate(),
            device_name=(device_name or "").strip()[:120],
        )
        self.save(identity)
        logger.info(
            "本机 Ed25519 设备身份已生成: installation=%s path=%s",
            identity.installation_id,
            self.path,
        )
        return identity

    def mark_enrolled(
        self,
        identity: DeviceIdentity,
        *,
        tenant_id: str,
        device_id: str,
        server_base_url: str,
    ) -> DeviceIdentity:
        if not is_valid_device_id(device_id):
            raise ValueError("server returned an invalid device_id")
        enrolled = replace(
            identity,
            tenant_id=normalize_tenant_id(tenant_id),
            device_id=device_id,
            server_base_url=(server_base_url or "").rstrip("/"),
            enrolled_at=time.time(),
        )
        self.save(enrolled)
        return enrolled

    def save(self, identity: DeviceIdentity) -> None:
        with self._lock:
            private_key_raw = identity.private_key.private_bytes(
                serialization.Encoding.Raw,
                serialization.PrivateFormat.Raw,
                serialization.NoEncryption(),
            )
            protection, protected = self._protect_private_key(private_key_raw)
            payload = {
                "version": 1,
                "installationId": identity.installation_id,
                "tenantId": identity.tenant_id,
                "deviceId": identity.device_id,
                "serverBaseUrl": identity.server_base_url,
                "deviceName": identity.device_name,
                "enrolledAt": identity.enrolled_at,
                "publicKey": identity.public_key_base64,
                "privateKeyProtection": protection,
                "protectedPrivateKey": encode_base64url(protected),
            }
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            if os.name != "nt":
                os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)

    @staticmethod
    def _protect_private_key(value: bytes) -> tuple[str, bytes]:
        if os.name == "nt":
            return "windows-dpapi-user", _dpapi_protect(value)
        logger.warning("当前系统不支持 DPAPI，开发环境使用 0600 文件权限保护设备私钥")
        return "file-0600", value

    @staticmethod
    def _unprotect_private_key(payload: dict) -> bytes:
        protected = decode_base64url(
            str(payload.get("protectedPrivateKey") or ""), expected_length=None
        )
        protection = str(payload.get("privateKeyProtection") or "")
        if protection == "windows-dpapi-user":
            if os.name != "nt":
                raise RuntimeError(
                    "Windows DPAPI identity cannot be opened on this platform"
                )
            raw = _dpapi_unprotect(protected)
        elif protection == "file-0600" and os.name != "nt":
            raw = protected
        else:
            raise RuntimeError(f"unsupported private key protection: {protection}")
        if len(raw) != 32:
            raise ValueError("invalid Ed25519 private key length")
        return raw


if os.name == "nt":

    class _DataBlob(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
        ]

    def _as_blob(value: bytes):
        buffer = ctypes.create_string_buffer(value)
        blob = _DataBlob(
            len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
        )
        return blob, buffer

    def _dpapi_call(function_name: str, value: bytes) -> bytes:
        value_blob, value_buffer = _as_blob(value)
        entropy_blob, entropy_buffer = _as_blob(_DPAPI_ENTROPY)
        output_blob = _DataBlob()
        function = getattr(ctypes.windll.crypt32, function_name)
        flags = 0x01  # CRYPTPROTECT_UI_FORBIDDEN
        if function_name == "CryptProtectData":
            ok = function(
                ctypes.byref(value_blob),
                "CVClient device identity",
                ctypes.byref(entropy_blob),
                None,
                None,
                flags,
                ctypes.byref(output_blob),
            )
        else:
            description = wintypes.LPWSTR()
            ok = function(
                ctypes.byref(value_blob),
                ctypes.byref(description),
                ctypes.byref(entropy_blob),
                None,
                None,
                flags,
                ctypes.byref(output_blob),
            )
        _ = value_buffer, entropy_buffer
        if not ok:
            raise ctypes.WinError()
        try:
            return ctypes.string_at(output_blob.pbData, output_blob.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(output_blob.pbData)

    def _dpapi_protect(value: bytes) -> bytes:
        return _dpapi_call("CryptProtectData", value)

    def _dpapi_unprotect(value: bytes) -> bytes:
        return _dpapi_call("CryptUnprotectData", value)
else:

    def _dpapi_protect(value: bytes) -> bytes:
        raise RuntimeError("DPAPI is only available on Windows")

    def _dpapi_unprotect(value: bytes) -> bytes:
        raise RuntimeError("DPAPI is only available on Windows")


_identity_cache: tuple[Path, DeviceIdentity] | None = None
_identity_cache_lock = threading.Lock()


def get_enrolled_device_identity(
    expected_server_base_url: str = "",
) -> DeviceIdentity | None:
    global _identity_cache
    path = DeviceIdentityStore.default_path()
    with _identity_cache_lock:
        if _identity_cache is None or _identity_cache[0] != path:
            identity = DeviceIdentityStore(path).load()
            if identity is None or not identity.enrolled:
                return None
            _identity_cache = (path, identity)
        identity = _identity_cache[1]
    expected = (expected_server_base_url or "").rstrip("/")
    if expected and identity.server_base_url != expected:
        raise RuntimeError(
            "设备身份绑定的服务器与 API_BASE_URL 不一致，禁止向其他服务器发送签名"
        )
    return identity

"""HMAC authentication helpers for protected integration APIs."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import time
from dataclasses import dataclass

from config import (
    API_KEY,
    API_SECRET,
    RUNTIME_DEFAULT_TENANT_ID,
    TENANT_API_CREDENTIALS_JSON,
)
from core.tenant import normalize_tenant_id


logger = logging.getLogger("uvicorn.error")


@dataclass(frozen=True, slots=True)
class TenantContext:
    tenant_id: str
    api_key: str = ""
    credential_source: str = ""
    auth_method: str = "hmac"
    principal_id: str = ""
    principal_name: str = ""
    tenant_name: str = ""
    device_id: str = ""


@dataclass(frozen=True, slots=True)
class _TenantCredential:
    tenant_id: str
    api_key: str
    secret: str
    source: str


class TenantCredentialRegistry:
    """Maps an external API key to exactly one trusted tenant."""

    def __init__(self, credentials: dict[str, _TenantCredential]) -> None:
        self._credentials = credentials

    @classmethod
    def from_mapping(
        cls,
        mapping: dict[str, object] | None,
        *,
        legacy_api_key: str = "",
        legacy_api_secret: str = "",
        legacy_tenant_id: str = RUNTIME_DEFAULT_TENANT_ID,
    ) -> "TenantCredentialRegistry":
        credentials: dict[str, _TenantCredential] = {}
        if legacy_api_key and legacy_api_secret:
            credentials[legacy_api_key] = _TenantCredential(
                tenant_id=normalize_tenant_id(legacy_tenant_id),
                api_key=legacy_api_key,
                secret=legacy_api_secret,
                source="legacy-default",
            )
        for api_key, value in (mapping or {}).items():
            if not isinstance(value, dict):
                raise RuntimeError("tenant credential entries must be objects")
            secret = str(value.get("secret") or "")
            raw_tenant_id = str(value.get("tenant_id") or "").strip()
            api_key = str(api_key or "").strip()
            if not api_key or not secret or not raw_tenant_id:
                raise RuntimeError(
                    "tenant credential api_key, tenant_id and secret are required"
                )
            tenant_id = normalize_tenant_id(raw_tenant_id)
            if api_key in credentials:
                raise RuntimeError("duplicate tenant API key in credential registry")
            credentials[api_key] = _TenantCredential(
                tenant_id=tenant_id,
                api_key=api_key,
                secret=secret,
                source="tenant-registry",
            )
        logger.info(
            "租户凭证注册表已加载: credentials=%d tenants=%d",
            len(credentials),
            len({item.tenant_id for item in credentials.values()}),
        )
        return cls(credentials)

    @classmethod
    def from_config(cls) -> "TenantCredentialRegistry":
        raw: dict[str, object] = {}
        if TENANT_API_CREDENTIALS_JSON:
            try:
                decoded = json.loads(TENANT_API_CREDENTIALS_JSON)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    "TENANT_API_CREDENTIALS_JSON is invalid JSON"
                ) from exc
            if not isinstance(decoded, dict):
                raise RuntimeError("TENANT_API_CREDENTIALS_JSON must be an object")
            raw = decoded
        return cls.from_mapping(
            raw,
            legacy_api_key=API_KEY,
            legacy_api_secret=API_SECRET,
            legacy_tenant_id=RUNTIME_DEFAULT_TENANT_ID,
        )

    def authenticate(
        self,
        *,
        method: str,
        path: str,
        timestamp: str | None,
        body: bytes,
        api_key: str | None,
        signature: str | None,
        tolerance_seconds: int,
    ) -> TenantContext | None:
        credential = self._credentials.get(api_key or "")
        if credential is None:
            return None
        if not verify_request_signature(
            expected_key=credential.api_key,
            secret=credential.secret,
            method=method,
            path=path,
            timestamp=timestamp,
            body=body,
            api_key=api_key,
            signature=signature,
            tolerance_seconds=tolerance_seconds,
        ):
            return None
        return TenantContext(
            tenant_id=credential.tenant_id,
            api_key=credential.api_key,
            credential_source=credential.source,
            auth_method="hmac",
            principal_id=credential.api_key,
        )


_tenant_registry: TenantCredentialRegistry | None = None


def get_tenant_credential_registry() -> TenantCredentialRegistry:
    global _tenant_registry
    if _tenant_registry is None:
        _tenant_registry = TenantCredentialRegistry.from_config()
    return _tenant_registry


def build_signature_payload(
    method: str,
    path: str,
    timestamp: str,
    body: bytes,
) -> bytes:
    prefix = f"{method.upper()}\n{path}\n{timestamp}\n".encode("utf-8")
    return prefix + body


def sign_request(
    secret: str,
    method: str,
    path: str,
    timestamp: str,
    body: bytes,
) -> str:
    payload = build_signature_payload(method, path, timestamp, body)
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def is_valid_timestamp(timestamp: str, tolerance_seconds: int) -> bool:
    try:
        value = int(timestamp)
    except (TypeError, ValueError):
        return False
    return abs(int(time.time()) - value) <= tolerance_seconds


def verify_request_signature(
    *,
    expected_key: str,
    secret: str,
    method: str,
    path: str,
    timestamp: str | None,
    body: bytes,
    api_key: str | None,
    signature: str | None,
    tolerance_seconds: int,
) -> bool:
    if not expected_key or not secret:
        return False
    if api_key != expected_key or not timestamp or not signature:
        return False
    if not is_valid_timestamp(timestamp, tolerance_seconds):
        return False
    expected_signature = sign_request(secret, method, path, timestamp, body)
    return hmac.compare_digest(signature, expected_signature)


_DEVICE_ALLOWED_ROUTES = (
    ("GET", re.compile(r"^/api/v1/attendance/today/[^/]+$")),
    ("POST", re.compile(r"^/api/v1/recognition/frame$")),
    ("POST", re.compile(r"^/api/v1/recognition/check-out$")),
    ("GET", re.compile(r"^/api/v1/client-tasks/next$")),
    ("POST", re.compile(r"^/api/v1/client-tasks/[^/]+/complete$")),
    ("POST", re.compile(r"^/api/v1/employees/enroll-embeddings$")),
    ("POST", re.compile(r"^/api/v1/device-sessions/avatar-bootstrap$")),
    ("POST", re.compile(r"^/api/v1/device-sessions/avatar-state-session$")),
)
_AVATAR_ALLOWED_ROUTES = (
    ("POST", re.compile(r"^/api/v1/dialog/chat$")),
    ("POST", re.compile(r"^/api/v1/dialog/voice-ticket$")),
    ("GET", re.compile(r"^/api/v1/avatar/persona$")),
    ("POST", re.compile(r"^/api/v1/client-tasks$")),
    ("GET", re.compile(r"^/api/v1/device-sessions/avatar-session$")),
)


def context_allows_request(context: TenantContext, method: str, path: str) -> bool:
    """Enforce least-privilege paths for device and browser principals."""

    if context.auth_method == "hmac":
        return True
    if context.auth_method == "tenant-admin":
        return path.startswith("/api/v1/")
    routes = (
        _DEVICE_ALLOWED_ROUTES
        if context.auth_method == "device"
        else _AVATAR_ALLOWED_ROUTES
        if context.auth_method == "avatar-session"
        else ()
    )
    method = method.upper()
    return any(
        route_method == method and pattern.fullmatch(path)
        for route_method, pattern in routes
    )

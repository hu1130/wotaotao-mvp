"""HMAC request signing helpers for API-only clients."""

from __future__ import annotations

import hashlib
import hmac


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

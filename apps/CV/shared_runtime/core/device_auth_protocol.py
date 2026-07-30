"""Canonical Ed25519 request protocol shared by client and server."""

from __future__ import annotations

import base64
import hashlib
import re


DEVICE_ID_RE = re.compile(r"^[a-zA-Z0-9._:-]{3,80}$")
NONCE_RE = re.compile(r"^[a-zA-Z0-9_-]{16,96}$")


def build_device_signature_payload(
    method: str,
    path: str,
    timestamp: str,
    nonce: str,
    body: bytes,
) -> bytes:
    """Build a bounded canonical payload without copying a large body twice."""

    body_digest = hashlib.sha256(body).hexdigest()
    return (f"{method.upper()}\n{path}\n{timestamp}\n{nonce}\n{body_digest}\n").encode(
        "utf-8"
    )


def build_enrollment_proof_payload(
    activation_code: str,
    installation_id: str,
    public_key_base64: str,
) -> bytes:
    activation_digest = hashlib.sha256(
        (activation_code or "").strip().encode("utf-8")
    ).hexdigest()
    return (
        "CVCLIENT-ENROLLMENT-V1\n"
        f"{installation_id}\n{public_key_base64}\n{activation_digest}\n"
    ).encode("utf-8")


def encode_base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def decode_base64url(value: str, *, expected_length: int | None = None) -> bytes:
    raw = (value or "").strip()
    if not raw or len(raw) > 512:
        raise ValueError("invalid base64url value")
    padding = "=" * (-len(raw) % 4)
    try:
        decoded = base64.b64decode(
            raw + padding,
            altchars=b"-_",
            validate=True,
        )
    except (ValueError, TypeError) as exc:
        raise ValueError("invalid base64url value") from exc
    if expected_length is not None and len(decoded) != expected_length:
        raise ValueError("invalid decoded length")
    return decoded


def is_valid_device_id(value: str) -> bool:
    return bool(DEVICE_ID_RE.fullmatch((value or "").strip()))


def is_valid_nonce(value: str) -> bool:
    return bool(NONCE_RE.fullmatch((value or "").strip()))

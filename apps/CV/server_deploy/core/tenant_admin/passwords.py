"""Versioned scrypt password hashing for tenant administrators."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets


_VERSION = "scrypt-v1"
_N = 2**14
_R = 8
_P = 1
_DKLEN = 32


def validate_password(password: str) -> str:
    value = password or ""
    if len(value) < 12:
        raise ValueError("管理员密码至少需要 12 个字符")
    if len(value) > 256:
        raise ValueError("管理员密码不能超过 256 个字符")
    return value


def hash_password(password: str, *, enforce_policy: bool = True) -> str:
    """Hash a password; policy can be relaxed only for legacy bootstrap."""

    value = validate_password(password) if enforce_policy else (password or "")
    if not value:
        raise ValueError("管理员密码不能为空")
    if len(value) > 256:
        raise ValueError("管理员密码不能超过 256 个字符")
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(
        value.encode("utf-8"),
        salt=salt,
        n=_N,
        r=_R,
        p=_P,
        dklen=_DKLEN,
    )
    return "$".join(
        (_VERSION, str(_N), str(_R), str(_P), _b64(salt), _b64(derived))
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        version, raw_n, raw_r, raw_p, raw_salt, raw_hash = encoded.split("$", 5)
        if version != _VERSION:
            return False
        n, r, p = int(raw_n), int(raw_r), int(raw_p)
        if n > 2**16 or r > 16 or p > 4:
            return False
        salt = _unb64(raw_salt)
        expected = _unb64(raw_hash)
        actual = hashlib.scrypt(
            (password or "").encode("utf-8"),
            salt=salt,
            n=n,
            r=r,
            p=p,
            dklen=len(expected),
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))

"""Canonical tenant identifiers shared by client and server runtimes."""

from __future__ import annotations

import hashlib
import re


DEFAULT_TENANT_ID = "default"
_SAFE_PART_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def normalize_tenant_id(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return DEFAULT_TENANT_ID
    normalized = _SAFE_PART_RE.sub("-", raw).strip("-._")
    if not normalized:
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
        normalized = f"tenant-{digest}"
    return normalized[:64]


def tenant_subject_id(tenant_id: str, employee_uuid: str) -> str:
    return f"tenant:{normalize_tenant_id(tenant_id)}:employee:{employee_uuid}"


def subject_belongs_to_tenant(person_id: str, tenant_id: str) -> bool:
    return (person_id or "").startswith(f"tenant:{normalize_tenant_id(tenant_id)}:")

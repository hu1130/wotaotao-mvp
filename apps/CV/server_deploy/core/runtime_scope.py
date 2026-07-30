"""Stable tenant/device namespaces for process-local runtime state.

The current deployment has one tenant. Keeping tenant and device as explicit
dimensions prevents accidental cross-device state sharing now and lets storage
backends be partitioned by tenant later without changing business APIs again.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from core.tenant import normalize_tenant_id


_SAFE_PART_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def _normalize_part(value: str, *, fallback: str, max_length: int) -> str:
    raw = (value or "").strip()
    if not raw:
        return fallback
    normalized = _SAFE_PART_RE.sub("-", raw).strip("-._")
    if not normalized:
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
        normalized = f"id-{digest}"
    return normalized[:max_length]


@dataclass(frozen=True, slots=True)
class RuntimeScope:
    tenant_id: str
    device_id: str

    @classmethod
    def build(cls, tenant_id: str = "", device_id: str = "") -> "RuntimeScope":
        return cls(
            tenant_id=normalize_tenant_id(tenant_id),
            device_id=_normalize_part(
                device_id,
                fallback="frontdesk-001",
                max_length=80,
            ),
        )

    @property
    def key(self) -> str:
        return f"tenant={self.tenant_id}|device={self.device_id}"

    def to_dict(self) -> dict[str, str]:
        return {"tenant_id": self.tenant_id, "device_id": self.device_id}

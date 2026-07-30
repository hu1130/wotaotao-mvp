"""Value objects for the device identity control plane."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


class DeviceEnrollmentError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class DeviceRecord:
    device_id: str
    tenant_id: str
    installation_id: str
    public_key: bytes
    display_name: str
    status: str
    auth_version: int
    created_at: datetime | None = None
    last_seen_at: datetime | None = None

    @property
    def active(self) -> bool:
        return self.status == "active"


@dataclass(frozen=True, slots=True)
class EnrollmentResult:
    device: DeviceRecord
    idempotent: bool


@dataclass(frozen=True, slots=True)
class ActivationCodeSummary:
    activation_id: int
    tenant_id: str
    code_prefix: str
    label: str
    expires_at: datetime
    claimed_at: datetime | None
    claimed_device_id: str
    created_at: datetime
    activation_code: str = ""


@dataclass(frozen=True, slots=True)
class AvatarSessionBinding:
    tenant_id: str
    device_id: str
    expires_at: float

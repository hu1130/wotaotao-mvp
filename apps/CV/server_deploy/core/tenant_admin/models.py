"""Value objects for tenant control-console accounts and sessions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class TenantAdminAccount:
    account_id: int
    tenant_id: str
    tenant_name: str
    username: str
    display_name: str
    password_hash: str
    status: str
    auth_version: int
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_login_at: datetime | None = None

    @property
    def active(self) -> bool:
        return self.status == "active"


@dataclass(frozen=True, slots=True)
class TenantAdminSessionBinding:
    account_id: int
    tenant_id: str
    tenant_name: str
    username: str
    display_name: str
    auth_version: int
    expires_at: float

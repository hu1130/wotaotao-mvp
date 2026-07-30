"""Tenant administrator authentication and legacy default-account bootstrap."""

from __future__ import annotations

import logging
import threading

from config import (
    CONTROL_DEFAULT_TENANT_NAME,
    CONTROL_PASSWORD,
    CONTROL_USERNAME,
    RUNTIME_DEFAULT_TENANT_ID,
)

from .models import TenantAdminAccount
from .passwords import hash_password, verify_password
from .repository import TenantAdminRepository


logger = logging.getLogger(__name__)


class TenantAdminAuthenticationService:
    def __init__(self, repository: TenantAdminRepository | None = None) -> None:
        self.repository = repository or TenantAdminRepository()
        self._dummy_hash = hash_password("invalid-tenant-admin-password")

    def ensure_legacy_default_account(self) -> TenantAdminAccount | None:
        if not CONTROL_USERNAME or not CONTROL_PASSWORD:
            logger.warning("默认控制台管理员未自动创建: CONTROL_PASSWORD 为空")
            return None
        account = self.repository.create_account(
            tenant_id=RUNTIME_DEFAULT_TENANT_ID,
            tenant_name=CONTROL_DEFAULT_TENANT_NAME,
            username=CONTROL_USERNAME,
            display_name="系统管理员",
            password_hash=hash_password(CONTROL_PASSWORD, enforce_policy=False),
            if_missing=True,
        )
        logger.info(
            "默认租户控制台管理员已就绪: tenant=%s username=%s",
            account.tenant_id,
            account.username,
        )
        return account

    def authenticate(
        self, tenant_id: str, username: str, password: str
    ) -> TenantAdminAccount | None:
        account = self.repository.get_account(tenant_id, username)
        encoded = account.password_hash if account is not None else self._dummy_hash
        valid = verify_password(password, encoded)
        if account is None or not account.active or not valid:
            return None
        self.repository.record_login(account.account_id)
        logger.info(
            "租户管理员认证成功: tenant=%s username=%s account=%d",
            account.tenant_id,
            account.username,
            account.account_id,
        )
        return account


_service: TenantAdminAuthenticationService | None = None
_service_lock = threading.Lock()


def get_tenant_admin_auth_service() -> TenantAdminAuthenticationService:
    global _service
    if _service is not None:
        return _service
    with _service_lock:
        if _service is None:
            _service = TenantAdminAuthenticationService()
        return _service

"""MySQL persistence for tenant control-console administrator accounts."""

from __future__ import annotations

import re
import threading
from contextlib import contextmanager

from core.attendance_db import AttendanceDB
from core.tenant import normalize_tenant_id

from .models import TenantAdminAccount


_USERNAME_RE = re.compile(r"^[a-zA-Z0-9._@-]{3,64}$")
_schema_lock = threading.Lock()
_schema_ready = False


def normalize_admin_username(username: str) -> str:
    value = (username or "").strip().casefold()
    if not _USERNAME_RE.fullmatch(value):
        raise ValueError("管理员用户名只能包含字母、数字及 . _ @ -，长度 3-64")
    return value


class TenantAdminRepository:
    def __init__(self) -> None:
        self._attendance_db = AttendanceDB()
        self._ensure_schema_once()

    @contextmanager
    def _connection(self):
        with self._attendance_db._connection() as conn:
            yield conn

    def _ensure_schema_once(self) -> None:
        global _schema_ready
        if _schema_ready:
            return
        with _schema_lock:
            if _schema_ready:
                return
            with self._connection() as conn:
                cur = conn.cursor()
                try:
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS tenant_admin_accounts (
                            id BIGINT AUTO_INCREMENT PRIMARY KEY,
                            tenant_id VARCHAR(64) NOT NULL,
                            tenant_name VARCHAR(120) NOT NULL,
                            username VARCHAR(64) NOT NULL,
                            display_name VARCHAR(120) NOT NULL,
                            password_hash VARCHAR(255) NOT NULL,
                            status VARCHAR(16) NOT NULL DEFAULT 'active',
                            auth_version INT NOT NULL DEFAULT 1,
                            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                                ON UPDATE CURRENT_TIMESTAMP,
                            last_login_at DATETIME NULL,
                            UNIQUE KEY uq_tenant_admin_username (tenant_id, username),
                            KEY idx_tenant_admin_status (tenant_id, status)
                        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                        """
                    )
                finally:
                    cur.close()
            _schema_ready = True

    def create_account(
        self,
        *,
        tenant_id: str,
        tenant_name: str,
        username: str,
        display_name: str,
        password_hash: str,
        if_missing: bool = False,
    ) -> TenantAdminAccount:
        tenant_id = normalize_tenant_id(tenant_id)
        username = normalize_admin_username(username)
        tenant_name = self._clean_text(tenant_name, 120) or tenant_id
        display_name = self._clean_text(display_name, 120) or username
        with self._connection() as conn:
            cur = conn.cursor()
            try:
                insert_sql = (
                    "INSERT INTO tenant_admin_accounts "
                    "(tenant_id, tenant_name, username, display_name, password_hash) "
                    "VALUES (%s, %s, %s, %s, %s)"
                )
                if if_missing:
                    insert_sql += " ON DUPLICATE KEY UPDATE id=id"
                cur.execute(
                    insert_sql,
                    (
                        tenant_id,
                        tenant_name,
                        username,
                        display_name,
                        password_hash,
                    ),
                )
                account = self._select(cur, tenant_id, username)
            finally:
                cur.close()
        if account is None:
            raise RuntimeError("tenant admin account was not created")
        return account

    def get_account(self, tenant_id: str, username: str) -> TenantAdminAccount | None:
        tenant_id = normalize_tenant_id(tenant_id)
        try:
            username = normalize_admin_username(username)
        except ValueError:
            return None
        with self._connection() as conn:
            cur = conn.cursor()
            try:
                return self._select(cur, tenant_id, username)
            finally:
                cur.close()

    def get_account_by_id(self, account_id: int) -> TenantAdminAccount | None:
        with self._connection() as conn:
            cur = conn.cursor()
            try:
                cur.execute(self._select_sql() + " WHERE id=%s", (int(account_id),))
                row = cur.fetchone()
                return self._from_row(row) if row else None
            finally:
                cur.close()

    def update_password(self, tenant_id: str, username: str, password_hash: str) -> bool:
        with self._connection() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "UPDATE tenant_admin_accounts SET password_hash=%s, "
                    "auth_version=auth_version+1 "
                    "WHERE tenant_id=%s AND username=%s",
                    (
                        password_hash,
                        normalize_tenant_id(tenant_id),
                        normalize_admin_username(username),
                    ),
                )
                return cur.rowcount > 0
            finally:
                cur.close()

    def set_status(self, tenant_id: str, username: str, status: str) -> bool:
        if status not in {"active", "disabled"}:
            raise ValueError("status must be active or disabled")
        with self._connection() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "UPDATE tenant_admin_accounts SET status=%s, "
                    "auth_version=auth_version+1 "
                    "WHERE tenant_id=%s AND username=%s",
                    (
                        status,
                        normalize_tenant_id(tenant_id),
                        normalize_admin_username(username),
                    ),
                )
                return cur.rowcount > 0
            finally:
                cur.close()

    def record_login(self, account_id: int) -> None:
        with self._connection() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "UPDATE tenant_admin_accounts SET last_login_at=CURRENT_TIMESTAMP "
                    "WHERE id=%s",
                    (int(account_id),),
                )
            finally:
                cur.close()

    def list_accounts(self, tenant_id: str | None = None) -> list[TenantAdminAccount]:
        with self._connection() as conn:
            cur = conn.cursor()
            try:
                sql = self._select_sql()
                if tenant_id:
                    cur.execute(
                        sql + " WHERE tenant_id=%s ORDER BY username",
                        (normalize_tenant_id(tenant_id),),
                    )
                else:
                    cur.execute(sql + " ORDER BY tenant_id, username")
                return [self._from_row(row) for row in cur.fetchall()]
            finally:
                cur.close()

    @classmethod
    def _select(cls, cur, tenant_id: str, username: str) -> TenantAdminAccount | None:
        cur.execute(
            cls._select_sql() + " WHERE tenant_id=%s AND username=%s",
            (tenant_id, username),
        )
        row = cur.fetchone()
        return cls._from_row(row) if row else None

    @staticmethod
    def _select_sql() -> str:
        return (
            "SELECT id, tenant_id, tenant_name, username, display_name, "
            "password_hash, status, auth_version, created_at, updated_at, "
            "last_login_at "
            "FROM tenant_admin_accounts"
        )

    @staticmethod
    def _from_row(row) -> TenantAdminAccount:
        return TenantAdminAccount(
            account_id=int(row[0]),
            tenant_id=normalize_tenant_id(str(row[1])),
            tenant_name=str(row[2]),
            username=str(row[3]),
            display_name=str(row[4]),
            password_hash=str(row[5]),
            status=str(row[6]),
            auth_version=int(row[7]),
            created_at=row[8],
            updated_at=row[9],
            last_login_at=row[10],
        )

    @staticmethod
    def _clean_text(value: str, max_length: int) -> str:
        return "".join(ch for ch in (value or "").strip() if ch >= " ")[:max_length]

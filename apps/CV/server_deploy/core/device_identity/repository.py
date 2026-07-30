"""MySQL persistence for activation codes and registered devices."""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import threading
from contextlib import contextmanager

from core.attendance_db import AttendanceDB
from core.tenant import normalize_tenant_id

from .models import (
    ActivationCodeSummary,
    DeviceEnrollmentError,
    DeviceRecord,
    EnrollmentResult,
)


logger = logging.getLogger(__name__)
_schema_lock = threading.Lock()
_schema_ready = False


class DeviceIdentityRepository:
    """Owns the device control-plane schema and transactional claims."""

    def __init__(self) -> None:
        self._attendance_db = AttendanceDB()
        self._ensure_schema_once()

    @contextmanager
    def _connection(self):
        # AttendanceDB is the process-wide owner of the bounded MySQL pool.
        with self._attendance_db._connection() as conn:
            yield conn

    def _ensure_schema_once(self) -> None:
        global _schema_ready
        if _schema_ready:
            return
        with _schema_lock:
            if _schema_ready:
                return
            self._ensure_schema()
            _schema_ready = True
            logger.info("设备身份数据库表已就绪")

    def _ensure_schema(self) -> None:
        with self._connection() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS registered_devices (
                        device_id VARCHAR(80) PRIMARY KEY,
                        tenant_id VARCHAR(64) NOT NULL,
                        installation_id CHAR(36) NOT NULL,
                        public_key VARBINARY(32) NOT NULL,
                        display_name VARCHAR(120) NOT NULL DEFAULT '',
                        platform_info JSON NULL,
                        status VARCHAR(16) NOT NULL DEFAULT 'active',
                        auth_version INT NOT NULL DEFAULT 1,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        last_seen_at DATETIME NULL,
                        revoked_at DATETIME NULL,
                        UNIQUE KEY uq_registered_devices_installation (installation_id),
                        UNIQUE KEY uq_registered_devices_public_key (public_key),
                        KEY idx_registered_devices_tenant_status (tenant_id, status)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS device_activation_codes (
                        id BIGINT AUTO_INCREMENT PRIMARY KEY,
                        tenant_id VARCHAR(64) NOT NULL,
                        code_hash BINARY(32) NOT NULL,
                        code_prefix VARCHAR(16) NOT NULL,
                        activation_code VARCHAR(128) NULL,
                        label VARCHAR(120) NOT NULL DEFAULT '',
                        expires_at DATETIME NOT NULL,
                        claimed_at DATETIME NULL,
                        claimed_device_id VARCHAR(80) NULL,
                        claimed_installation_id CHAR(36) NULL,
                        created_by VARCHAR(120) NOT NULL DEFAULT 'cli',
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE KEY uq_device_activation_code_hash (code_hash),
                        KEY idx_device_activation_tenant_created (tenant_id, created_at),
                        KEY idx_device_activation_expiry (expires_at),
                        CONSTRAINT fk_activation_claimed_device
                            FOREIGN KEY (claimed_device_id)
                            REFERENCES registered_devices(device_id)
                            ON DELETE SET NULL
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                    """
                )
                cur.execute("SHOW COLUMNS FROM device_activation_codes LIKE 'activation_code'")
                if cur.fetchone() is None:
                    cur.execute(
                        """
                        ALTER TABLE device_activation_codes
                        ADD COLUMN activation_code VARCHAR(128) NULL AFTER code_prefix
                        """
                    )
            finally:
                cur.close()

    def create_activation_code(
        self,
        tenant_id: str,
        *,
        label: str = "",
        ttl_seconds: int,
        created_by: str = "cli",
    ) -> tuple[str, ActivationCodeSummary]:
        tenant_id = normalize_tenant_id(tenant_id)
        ttl_seconds = max(60, min(int(ttl_seconds), 30 * 24 * 3600))
        raw_code = f"act_{secrets.token_urlsafe(24)}"
        code_hash = self._hash_code(raw_code)
        code_prefix = raw_code[:12]
        with self._connection() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "INSERT INTO device_activation_codes "
                    "(tenant_id, code_hash, code_prefix, activation_code, label, expires_at, created_by) "
                    "VALUES (%s, %s, %s, %s, %s, DATE_ADD(CURRENT_TIMESTAMP, INTERVAL %s SECOND), %s)",
                    (
                        tenant_id,
                        code_hash,
                        code_prefix,
                        raw_code,
                        self._clean_text(label, 120),
                        ttl_seconds,
                        self._clean_text(created_by, 120) or "cli",
                    ),
                )
                activation_id = int(cur.lastrowid)
                cur.execute(
                    "SELECT id, tenant_id, code_prefix, activation_code, label, expires_at, claimed_at, "
                    "COALESCE(claimed_device_id, ''), created_at "
                    "FROM device_activation_codes WHERE id=%s",
                    (activation_id,),
                )
                summary = self._activation_from_row(cur.fetchone())
                if summary is None:
                    raise RuntimeError("created activation code disappeared after insert")
            finally:
                cur.close()
        logger.info(
            "设备激活码已创建: tenant=%s prefix=%s ttl=%ds label=%s",
            tenant_id,
            code_prefix,
            ttl_seconds,
            label or "-",
        )
        return raw_code, summary

    def claim_activation_code(
        self,
        *,
        activation_code: str,
        installation_id: str,
        public_key: bytes,
        display_name: str,
        platform_info: dict[str, object] | None,
    ) -> EnrollmentResult:
        code_hash = self._hash_code(activation_code)
        platform_json = json.dumps(
            platform_info or {}, ensure_ascii=False, separators=(",", ":")
        )[:4000]
        with self._connection() as conn:
            cur = conn.cursor()
            try:
                conn.begin()
                cur.execute(
                    "SELECT id, tenant_id, expires_at, claimed_at, "
                    "claimed_device_id, claimed_installation_id, "
                    "(expires_at <= CURRENT_TIMESTAMP) AS is_expired "
                    "FROM device_activation_codes WHERE code_hash=%s FOR UPDATE",
                    (code_hash,),
                )
                activation = cur.fetchone()
                if activation is None:
                    raise DeviceEnrollmentError(
                        "activation_invalid", "激活码无效或已被删除", status_code=401
                    )
                (
                    activation_id,
                    tenant_id,
                    _expires_at,
                    claimed_at,
                    claimed_device_id,
                    claimed_installation_id,
                    is_expired,
                ) = activation
                if claimed_at is not None:
                    if (
                        claimed_installation_id != installation_id
                        or not claimed_device_id
                    ):
                        raise DeviceEnrollmentError(
                            "activation_already_claimed",
                            "激活码已经被其他设备使用",
                            status_code=409,
                        )
                    device = self._select_device(
                        cur, claimed_device_id, for_update=True
                    )
                    if device is None or not secrets.compare_digest(
                        device.public_key, public_key
                    ):
                        raise DeviceEnrollmentError(
                            "activation_identity_mismatch",
                            "设备身份与已激活记录不匹配",
                            status_code=409,
                        )
                    if not device.active:
                        raise DeviceEnrollmentError(
                            "device_revoked", "设备已被停用", status_code=403
                        )
                    cur.execute(
                        "UPDATE registered_devices SET last_seen_at=CURRENT_TIMESTAMP "
                        "WHERE device_id=%s",
                        (device.device_id,),
                    )
                    conn.commit()
                    return EnrollmentResult(device=device, idempotent=True)
                if bool(is_expired):
                    raise DeviceEnrollmentError(
                        "activation_expired", "激活码已过期", status_code=410
                    )

                cur.execute(
                    "SELECT device_id FROM registered_devices "
                    "WHERE installation_id=%s OR public_key=%s LIMIT 1 FOR UPDATE",
                    (installation_id, public_key),
                )
                if cur.fetchone() is not None:
                    raise DeviceEnrollmentError(
                        "identity_already_registered",
                        "该设备身份已经注册，请使用原设备凭据启动",
                        status_code=409,
                    )

                device_id = self._new_device_id()
                cur.execute(
                    "INSERT INTO registered_devices "
                    "(device_id, tenant_id, installation_id, public_key, display_name, "
                    "platform_info, status, last_seen_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, 'active', CURRENT_TIMESTAMP)",
                    (
                        device_id,
                        normalize_tenant_id(tenant_id),
                        installation_id,
                        public_key,
                        self._clean_text(display_name, 120),
                        platform_json,
                    ),
                )
                cur.execute(
                    "UPDATE device_activation_codes SET claimed_at=CURRENT_TIMESTAMP, "
                    "claimed_device_id=%s, claimed_installation_id=%s, activation_code=NULL WHERE id=%s",
                    (device_id, installation_id, activation_id),
                )
                device = self._select_device(cur, device_id, for_update=False)
                conn.commit()
            except DeviceEnrollmentError:
                conn.rollback()
                raise
            except Exception:
                conn.rollback()
                raise
            finally:
                cur.close()
        if device is None:
            raise RuntimeError("registered device disappeared after insert")
        logger.info(
            "设备激活成功: tenant=%s device=%s installation=%s name=%s",
            device.tenant_id,
            device.device_id,
            installation_id,
            device.display_name or "-",
        )
        return EnrollmentResult(device=device, idempotent=False)

    def get_device(self, device_id: str) -> DeviceRecord | None:
        with self._connection() as conn:
            cur = conn.cursor()
            try:
                return self._select_device(cur, device_id, for_update=False)
            finally:
                cur.close()

    def touch_device(self, device_id: str, minimum_interval_seconds: int) -> None:
        with self._connection() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "UPDATE registered_devices SET last_seen_at=CURRENT_TIMESTAMP "
                    "WHERE device_id=%s AND status='active' AND "
                    "(last_seen_at IS NULL OR last_seen_at < "
                    "DATE_SUB(CURRENT_TIMESTAMP, INTERVAL %s SECOND))",
                    (device_id, max(1, int(minimum_interval_seconds))),
                )
            finally:
                cur.close()

    def set_device_status(self, device_id: str, status: str) -> bool:
        if status not in {"active", "revoked"}:
            raise ValueError("status must be active or revoked")
        with self._connection() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "UPDATE registered_devices SET status=%s, auth_version=auth_version+1, "
                    "revoked_at=IF(%s='revoked', CURRENT_TIMESTAMP, NULL) WHERE device_id=%s",
                    (status, status, device_id),
                )
                changed = cur.rowcount > 0
            finally:
                cur.close()
        logger.warning("设备状态已更新: device=%s status=%s", device_id, status)
        return changed

    def delete_device(self, device_id: str) -> DeviceRecord | None:
        device_id = (device_id or "").strip()
        if not device_id:
            return None
        with self._connection() as conn:
            cur = conn.cursor()
            try:
                conn.begin()
                device = self._select_device(cur, device_id, for_update=True)
                if device is None:
                    conn.rollback()
                    return None
                cur.execute(
                    "DELETE FROM registered_devices WHERE device_id=%s",
                    (device_id,),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                cur.close()
        logger.warning(
            "注册设备已删除: tenant=%s device=%s installation=%s",
            device.tenant_id,
            device.device_id,
            device.installation_id,
        )
        return device

    def list_devices(self, tenant_id: str | None = None) -> list[DeviceRecord]:
        with self._connection() as conn:
            cur = conn.cursor()
            try:
                if tenant_id:
                    cur.execute(
                        "SELECT device_id, tenant_id, installation_id, public_key, "
                        "display_name, status, auth_version, created_at, last_seen_at "
                        "FROM registered_devices WHERE tenant_id=%s ORDER BY created_at DESC",
                        (normalize_tenant_id(tenant_id),),
                    )
                else:
                    cur.execute(
                        "SELECT device_id, tenant_id, installation_id, public_key, "
                        "display_name, status, auth_version, created_at, last_seen_at "
                        "FROM registered_devices ORDER BY created_at DESC"
                    )
                return [self._device_from_row(row) for row in cur.fetchall()]
            finally:
                cur.close()

    def list_activation_codes(
        self, tenant_id: str | None = None, limit: int = 100
    ) -> list[ActivationCodeSummary]:
        limit = max(1, min(int(limit), 500))
        with self._connection() as conn:
            cur = conn.cursor()
            try:
                if tenant_id:
                    cur.execute(
                        "SELECT id, tenant_id, code_prefix, activation_code, label, expires_at, claimed_at, "
                        "COALESCE(claimed_device_id, ''), created_at "
                        "FROM device_activation_codes WHERE tenant_id=%s "
                        "ORDER BY id DESC LIMIT %s",
                        (normalize_tenant_id(tenant_id), limit),
                    )
                else:
                    cur.execute(
                        "SELECT id, tenant_id, code_prefix, activation_code, label, expires_at, claimed_at, "
                        "COALESCE(claimed_device_id, ''), created_at "
                        "FROM device_activation_codes ORDER BY id DESC LIMIT %s",
                        (limit,),
                    )
                return [self._activation_from_row(row) for row in cur.fetchall()]
            finally:
                cur.close()

    def delete_activation_code(
        self, *, tenant_id: str, activation_id: int
    ) -> ActivationCodeSummary | None:
        tenant_id = normalize_tenant_id(tenant_id)
        activation_id = int(activation_id)
        with self._connection() as conn:
            cur = conn.cursor()
            try:
                conn.begin()
                cur.execute(
                    "SELECT id, tenant_id, code_prefix, activation_code, label, expires_at, claimed_at, "
                    "COALESCE(claimed_device_id, ''), created_at "
                    "FROM device_activation_codes WHERE id=%s AND tenant_id=%s FOR UPDATE",
                    (activation_id, tenant_id),
                )
                summary = self._activation_from_row(cur.fetchone())
                if summary is None:
                    conn.rollback()
                    return None
                cur.execute(
                    "DELETE FROM device_activation_codes WHERE id=%s AND tenant_id=%s",
                    (activation_id, tenant_id),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                cur.close()
        logger.warning(
            "设备激活码已删除: tenant=%s activation_id=%s prefix=%s claimed=%s",
            tenant_id,
            activation_id,
            summary.code_prefix,
            summary.claimed_at is not None,
        )
        return summary

    def purge_tenant_devices(self, tenant_id: str) -> tuple[int, int]:
        """Delete only device-control-plane rows for an explicitly confirmed tenant."""

        tenant_id = normalize_tenant_id(tenant_id)
        with self._connection() as conn:
            cur = conn.cursor()
            try:
                conn.begin()
                cur.execute(
                    "DELETE FROM device_activation_codes WHERE tenant_id=%s",
                    (tenant_id,),
                )
                activation_count = cur.rowcount
                cur.execute(
                    "DELETE FROM registered_devices WHERE tenant_id=%s",
                    (tenant_id,),
                )
                device_count = cur.rowcount
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                cur.close()
        logger.warning(
            "租户设备控制面数据已清理: tenant=%s activations=%d devices=%d",
            tenant_id,
            activation_count,
            device_count,
        )
        return activation_count, device_count

    @staticmethod
    def _select_device(cur, device_id: str, *, for_update: bool) -> DeviceRecord | None:
        sql = (
            "SELECT device_id, tenant_id, installation_id, public_key, display_name, "
            "status, auth_version, created_at, last_seen_at "
            "FROM registered_devices WHERE device_id=%s"
        )
        if for_update:
            sql += " FOR UPDATE"
        cur.execute(sql, (device_id,))
        row = cur.fetchone()
        return DeviceIdentityRepository._device_from_row(row) if row else None

    @staticmethod
    def _device_from_row(row) -> DeviceRecord:
        return DeviceRecord(
            device_id=str(row[0]),
            tenant_id=normalize_tenant_id(str(row[1])),
            installation_id=str(row[2]),
            public_key=bytes(row[3]),
            display_name=str(row[4] or ""),
            status=str(row[5]),
            auth_version=int(row[6]),
            created_at=row[7],
            last_seen_at=row[8],
        )

    @staticmethod
    def _activation_from_row(row) -> ActivationCodeSummary | None:
        if row is None:
            return None
        return ActivationCodeSummary(
            activation_id=int(row[0]),
            tenant_id=normalize_tenant_id(str(row[1])),
            code_prefix=str(row[2]),
            activation_code=str(row[3] or ""),
            label=str(row[4] or ""),
            expires_at=row[5],
            claimed_at=row[6],
            claimed_device_id=str(row[7] or ""),
            created_at=row[8],
        )

    @staticmethod
    def _hash_code(value: str) -> bytes:
        return hashlib.sha256((value or "").strip().encode("utf-8")).digest()

    @staticmethod
    def _new_device_id() -> str:
        return f"dev_{secrets.token_urlsafe(15)}"

    @staticmethod
    def _clean_text(value: str, max_length: int) -> str:
        return "".join(ch for ch in (value or "").strip() if ch >= " ")[:max_length]

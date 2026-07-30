"""Stable employee identity resolution independent from mutable display names."""

from __future__ import annotations

import logging
import threading

import pymysql

from config import (
    MYSQL_CHARSET,
    MYSQL_DATABASE,
    MYSQL_HOST,
    MYSQL_PASSWORD,
    MYSQL_PORT,
    MYSQL_USER,
    MYSQL_TIME_ZONE,
)
from core.attendance_db import AttendanceDB
from core.concurrency import StripedLock
from core.tenant import DEFAULT_TENANT_ID, normalize_tenant_id, tenant_subject_id

logger = logging.getLogger("uvicorn.error")
_repository: PersonIdentityRepository | None = None
_repository_lock = threading.Lock()


class PersonIdentityRepository:
    """Resolves a display name to an immutable employee UUID stored in MySQL."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._resolve_locks = StripedLock(32)
        self._cache: dict[tuple[str, str], str] = {}
        self._ensure_schema()

    def resolve_person_id(
        self, name: str, tenant_id: str = DEFAULT_TENANT_ID
    ) -> str:
        name = (name or "").strip()
        if not name:
            return ""
        tenant_id = normalize_tenant_id(tenant_id)
        cache_key = (tenant_id, name)
        with self._lock:
            cached = self._cache.get(cache_key)
            if cached:
                return cached
        with self._resolve_locks.for_key(f"{tenant_id}|{name}"):
            with self._lock:
                cached = self._cache.get(cache_key)
                if cached:
                    return cached
            with self._connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT employee_uuid FROM employees "
                        "WHERE tenant_id = %s AND name = %s LIMIT 1",
                        (tenant_id, name),
                    )
                    row = cur.fetchone()
                    if row is None:
                        cur.execute(
                            "INSERT INTO employees (tenant_id, name, employee_uuid) "
                            "VALUES (%s, %s, UUID())",
                            (tenant_id, name),
                        )
                        cur.execute(
                            "SELECT employee_uuid FROM employees "
                            "WHERE tenant_id = %s AND name = %s LIMIT 1",
                            (tenant_id, name),
                        )
                        row = cur.fetchone()
                conn.commit()
            employee_uuid = str(row[0])
            person_id = tenant_subject_id(tenant_id, employee_uuid)
            with self._lock:
                self._cache[cache_key] = person_id
        logger.info(
            "稳定人物身份已解析: tenant=%s name=%s person=%s",
            tenant_id,
            name,
            _short_id(person_id),
        )
        return person_id

    def invalidate(self, name: str = "", tenant_id: str = "") -> None:
        with self._lock:
            if name:
                self._cache.pop((normalize_tenant_id(tenant_id), name.strip()), None)
            else:
                self._cache.clear()

    def _ensure_schema(self) -> None:
        AttendanceDB()
        logger.info("员工稳定 UUID 字段已就绪")

    @staticmethod
    def _connection():
        return pymysql.connect(
            host=MYSQL_HOST,
            port=MYSQL_PORT,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            database=MYSQL_DATABASE,
            charset=MYSQL_CHARSET,
            autocommit=False,
            cursorclass=pymysql.cursors.Cursor,
            connect_timeout=10,
            read_timeout=15,
            write_timeout=15,
            init_command=f"SET time_zone = '{MYSQL_TIME_ZONE}'",
        )


def _short_id(person_id: str) -> str:
    return person_id if len(person_id) <= 18 else f"{person_id[:10]}…{person_id[-6:]}"


def get_person_identity_repository() -> PersonIdentityRepository:
    global _repository
    if _repository is None:
        with _repository_lock:
            if _repository is None:
                _repository = PersonIdentityRepository()
    return _repository

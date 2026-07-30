"""MySQL persistence for tenant avatar persona settings."""

from __future__ import annotations

import json
import threading
from contextlib import contextmanager

from core.attendance_db import AttendanceDB
from core.tenant import normalize_tenant_id

from .models import TenantAvatarPersona


_schema_lock = threading.Lock()
_schema_ready = False


class TenantAvatarPersonaRepository:
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
                        CREATE TABLE IF NOT EXISTS tenant_avatar_personas (
                            tenant_id VARCHAR(64) NOT NULL PRIMARY KEY,
                            assistant_name VARCHAR(80) NOT NULL DEFAULT '',
                            personality VARCHAR(600) NOT NULL DEFAULT '',
                            speaking_tone VARCHAR(600) NOT NULL DEFAULT '',
                            extra_instructions VARCHAR(1000) NOT NULL DEFAULT '',
                            wake_aliases_json JSON NOT NULL,
                            version BIGINT NOT NULL DEFAULT 1,
                            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                                ON UPDATE CURRENT_TIMESTAMP
                        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                        """
                    )
                finally:
                    cur.close()
            _schema_ready = True

    def get(self, tenant_id: str) -> TenantAvatarPersona | None:
        tenant_id = normalize_tenant_id(tenant_id)
        with self._connection() as conn:
            cur = conn.cursor()
            try:
                cur.execute(self._select_sql() + " WHERE tenant_id=%s", (tenant_id,))
                row = cur.fetchone()
                return self._from_row(row) if row else None
            finally:
                cur.close()

    def upsert(self, persona: TenantAvatarPersona) -> TenantAvatarPersona:
        tenant_id = normalize_tenant_id(persona.tenant_id)
        with self._connection() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    """
                    INSERT INTO tenant_avatar_personas (
                        tenant_id, assistant_name, personality, speaking_tone,
                        extra_instructions, wake_aliases_json, version
                    ) VALUES (%s, %s, %s, %s, %s, %s, 1)
                    ON DUPLICATE KEY UPDATE
                        assistant_name=VALUES(assistant_name),
                        personality=VALUES(personality),
                        speaking_tone=VALUES(speaking_tone),
                        extra_instructions=VALUES(extra_instructions),
                        wake_aliases_json=VALUES(wake_aliases_json),
                        version=version+1
                    """,
                    (
                        tenant_id,
                        persona.assistant_name,
                        persona.personality,
                        persona.speaking_tone,
                        persona.extra_instructions,
                        json.dumps(list(persona.wake_aliases), ensure_ascii=False),
                    ),
                )
            finally:
                cur.close()
        saved = self.get(tenant_id)
        if saved is None:
            raise RuntimeError("tenant avatar persona was not persisted")
        return saved

    @staticmethod
    def _select_sql() -> str:
        return (
            "SELECT tenant_id, assistant_name, personality, speaking_tone, "
            "extra_instructions, wake_aliases_json, version, created_at, updated_at "
            "FROM tenant_avatar_personas"
        )

    @staticmethod
    def _from_row(row) -> TenantAvatarPersona:
        aliases = row[5]
        if isinstance(aliases, str):
            aliases = json.loads(aliases or "[]")
        return TenantAvatarPersona(
            tenant_id=normalize_tenant_id(str(row[0])),
            assistant_name=str(row[1] or ""),
            personality=str(row[2] or ""),
            speaking_tone=str(row[3] or ""),
            extra_instructions=str(row[4] or ""),
            wake_aliases=tuple(str(item) for item in aliases or () if str(item).strip()),
            version=int(row[6]),
            created_at=row[7],
            updated_at=row[8],
        )

"""MySQL persistence for one versioned voice profile per tenant."""

from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from core.attendance_db import AttendanceDB
from core.tenant import normalize_tenant_id

from .models import TenantVoiceProfile


_schema_lock = threading.Lock()
_schema_ready = False


class TenantVoiceProfileRepository:
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
                        CREATE TABLE IF NOT EXISTS tenant_voice_profiles (
                            tenant_id VARCHAR(64) NOT NULL PRIMARY KEY,
                            provider VARCHAR(32) NOT NULL DEFAULT 'volcengine',
                            enabled TINYINT(1) NOT NULL DEFAULT 0,
                            status VARCHAR(24) NOT NULL DEFAULT 'draft',
                            speaker_id VARCHAR(160) NOT NULL,
                            fallback_speaker_id VARCHAR(160) NOT NULL,
                            omni_model VARCHAR(32) NOT NULL,
                            realtime_resource_id VARCHAR(80) NOT NULL,
                            training_resource_id VARCHAR(80) NOT NULL,
                            tts_2_0_model VARCHAR(32) NOT NULL,
                            speech_persona_json JSON NOT NULL,
                            sample_sha256 CHAR(64) NOT NULL,
                            consent_reference VARCHAR(255) NOT NULL,
                            version BIGINT NOT NULL DEFAULT 1,
                            last_probe_at DATETIME NULL,
                            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                                ON UPDATE CURRENT_TIMESTAMP,
                            KEY idx_tenant_voice_state (status, enabled)
                        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                        """
                    )
                finally:
                    cur.close()
            _schema_ready = True

    def get(self, tenant_id: str) -> TenantVoiceProfile | None:
        tenant_id = normalize_tenant_id(tenant_id)
        with self._connection() as conn:
            cur = conn.cursor()
            try:
                cur.execute(self._select_sql() + " WHERE tenant_id=%s", (tenant_id,))
                row = cur.fetchone()
                return self._from_row(row) if row else None
            finally:
                cur.close()

    def register(self, profile: TenantVoiceProfile) -> TenantVoiceProfile:
        tenant_id = normalize_tenant_id(profile.tenant_id)
        with self._connection() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    """
                    INSERT INTO tenant_voice_profiles (
                        tenant_id, provider, enabled, status, speaker_id,
                        fallback_speaker_id, omni_model, realtime_resource_id,
                        training_resource_id, tts_2_0_model, speech_persona_json,
                        sample_sha256, consent_reference, version, last_probe_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1, %s)
                    ON DUPLICATE KEY UPDATE
                        provider=VALUES(provider), enabled=0, status=VALUES(status),
                        speaker_id=VALUES(speaker_id),
                        fallback_speaker_id=VALUES(fallback_speaker_id),
                        omni_model=VALUES(omni_model),
                        realtime_resource_id=VALUES(realtime_resource_id),
                        training_resource_id=VALUES(training_resource_id),
                        tts_2_0_model=VALUES(tts_2_0_model),
                        speech_persona_json=VALUES(speech_persona_json),
                        sample_sha256=VALUES(sample_sha256),
                        consent_reference=VALUES(consent_reference),
                        last_probe_at=VALUES(last_probe_at), version=version+1
                    """,
                    (
                        tenant_id,
                        profile.provider,
                        int(profile.enabled),
                        profile.status,
                        profile.speaker_id,
                        profile.fallback_speaker_id,
                        profile.omni_model,
                        profile.realtime_resource_id,
                        profile.training_resource_id,
                        profile.tts_2_0_model,
                        json.dumps(profile.speech_persona, ensure_ascii=False),
                        profile.sample_sha256,
                        profile.consent_reference,
                        profile.last_probe_at,
                    ),
                )
            finally:
                cur.close()
        saved = self.get(tenant_id)
        if saved is None:
            raise RuntimeError("tenant voice profile was not persisted")
        return saved

    def set_enabled(self, tenant_id: str, enabled: bool) -> TenantVoiceProfile | None:
        tenant_id = normalize_tenant_id(tenant_id)
        with self._connection() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "UPDATE tenant_voice_profiles SET enabled=%s, version=version+1 "
                    "WHERE tenant_id=%s",
                    (int(enabled), tenant_id),
                )
                if cur.rowcount <= 0:
                    return None
            finally:
                cur.close()
        return self.get(tenant_id)

    @staticmethod
    def _select_sql() -> str:
        return (
            "SELECT tenant_id, provider, enabled, status, speaker_id, "
            "fallback_speaker_id, omni_model, realtime_resource_id, "
            "training_resource_id, tts_2_0_model, speech_persona_json, "
            "sample_sha256, consent_reference, version, last_probe_at, "
            "created_at, updated_at FROM tenant_voice_profiles"
        )

    @staticmethod
    def _from_row(row) -> TenantVoiceProfile:
        persona = row[10]
        if isinstance(persona, str):
            persona = json.loads(persona or "{}")
        return TenantVoiceProfile(
            tenant_id=normalize_tenant_id(str(row[0])),
            provider=str(row[1]),
            enabled=bool(row[2]),
            status=str(row[3]),
            speaker_id=str(row[4]),
            fallback_speaker_id=str(row[5]),
            omni_model=str(row[6]),
            realtime_resource_id=str(row[7]),
            training_resource_id=str(row[8]),
            tts_2_0_model=str(row[9]),
            speech_persona=dict(persona or {}),
            sample_sha256=str(row[11]),
            consent_reference=str(row[12]),
            version=int(row[13]),
            last_probe_at=row[14],
            created_at=row[15],
            updated_at=row[16],
        )

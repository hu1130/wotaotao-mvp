"""Immutable value objects for tenant voice configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any


@dataclass(frozen=True, slots=True)
class OmniSessionSettings:
    tenant_id: str
    speaker_id: str
    fallback_speaker_id: str
    model: str
    realtime_resource_id: str
    training_resource_id: str
    tts_2_0_model: str
    speaking_style: str
    profile_version: int
    clone_enabled: bool


@dataclass(frozen=True, slots=True)
class TenantVoiceProfile:
    tenant_id: str
    provider: str
    enabled: bool
    status: str
    speaker_id: str
    fallback_speaker_id: str
    omni_model: str
    realtime_resource_id: str
    training_resource_id: str
    tts_2_0_model: str
    speech_persona: dict[str, Any] = field(default_factory=dict)
    sample_sha256: str = ""
    consent_reference: str = ""
    version: int = 0
    last_probe_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def probe_is_fresh(self, ttl_seconds: int, now: datetime | None = None) -> bool:
        if self.last_probe_at is None:
            return False
        if ttl_seconds <= 0:
            return True
        now = now or datetime.now()
        return self.last_probe_at >= now - timedelta(seconds=max(1, ttl_seconds))

    @property
    def speaking_style(self) -> str:
        return str(self.speech_persona.get("speaking_style") or "").strip()

    def to_settings(self, *, clone_enabled: bool) -> OmniSessionSettings:
        return OmniSessionSettings(
            tenant_id=self.tenant_id,
            speaker_id=(self.speaker_id if clone_enabled else self.fallback_speaker_id),
            fallback_speaker_id=self.fallback_speaker_id,
            model=self.omni_model,
            realtime_resource_id=self.realtime_resource_id,
            training_resource_id=self.training_resource_id,
            tts_2_0_model=(self.tts_2_0_model if clone_enabled else ""),
            speaking_style=(self.speaking_style if clone_enabled else ""),
            profile_version=self.version,
            clone_enabled=clone_enabled,
        )

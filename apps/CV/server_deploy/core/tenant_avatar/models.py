"""Tenant-scoped avatar persona settings."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True, slots=True)
class TenantAvatarPersona:
    tenant_id: str
    assistant_name: str = ""
    personality: str = ""
    speaking_tone: str = ""
    extra_instructions: str = ""
    wake_aliases: tuple[str, ...] = field(default_factory=tuple)
    version: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class AvatarPersonaSettings:
    tenant_id: str
    assistant_name: str
    wake_aliases: tuple[str, ...]
    custom_wake_aliases: tuple[str, ...]
    system_role: str
    chat_system_prompt: str
    speaking_style: str
    personality: str
    speaking_tone: str
    extra_instructions: str
    customized: bool
    version: int

    def to_public_dict(self) -> dict:
        return {
            "tenantId": self.tenant_id,
            "assistantName": self.assistant_name,
            "wakeAliases": list(self.wake_aliases),
            "customWakeAliases": list(self.custom_wake_aliases),
            "personality": self.personality,
            "speakingTone": self.speaking_tone,
            "extraInstructions": self.extra_instructions,
            "customized": self.customized,
            "version": self.version,
        }

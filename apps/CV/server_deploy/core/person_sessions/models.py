"""Domain models for camera-driven person conversations."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class PersonSessionState(StrEnum):
    IDLE = "idle"
    CANDIDATE = "candidate"
    ACTIVE = "active"
    OWNER_GRACE = "owner_grace"
    SUSPENDED_IDLE = "suspended_idle"


@dataclass(frozen=True)
class ObservedPerson:
    person_id: str
    person_name: str
    track_id: int
    similarity: float
    area: int
    center_distance: float


@dataclass
class DevicePersonSession:
    device_id: str
    tenant_id: str = "default"
    state: PersonSessionState = PersonSessionState.IDLE
    conversation_id: str = ""
    owner_id: str = ""
    owner_name: str = ""
    owner_last_seen_at: float = 0.0
    owner_absent_since: float = 0.0
    started_at: float = 0.0
    last_activity_at: float = 0.0
    candidate_id: str = ""
    candidate_name: str = ""
    candidate_since: float = 0.0
    participants: tuple[str, ...] = field(default_factory=tuple)
    last_observed_at: float = 0.0
    privacy_epoch: int = 0


@dataclass(frozen=True)
class PersonSessionSnapshot:
    device_id: str
    state: PersonSessionState
    tenant_id: str = "default"
    conversation_id: str = ""
    owner_id: str = ""
    owner_name: str = ""
    participants: tuple[str, ...] = field(default_factory=tuple)
    started_at: float = 0.0
    last_activity_at: float = 0.0
    owner_absent_seconds: float = 0.0
    privacy_epoch: int = 0

    @property
    def has_owner(self) -> bool:
        return bool(self.owner_id)

    @property
    def bystanders_present(self) -> bool:
        return bool(self.participants)

    @property
    def memory_read_allowed(self) -> bool:
        return self.has_owner

    @property
    def memory_write_allowed(self) -> bool:
        return self.has_owner and bool(self.conversation_id)

    @property
    def should_release_voice(self) -> bool:
        return self.state in {PersonSessionState.IDLE, PersonSessionState.SUSPENDED_IDLE}

    def to_dict(self) -> dict:
        return {
            "tenant_id": self.tenant_id,
            "device_id": self.device_id,
            "state": self.state.value,
            "conversation_id": self.conversation_id,
            "owner": {
                "person_id": self.owner_id,
                "person_name": self.owner_name,
            }
            if self.has_owner
            else None,
            "participants": list(self.participants),
            "bystanders_present": self.bystanders_present,
            "memory_read_allowed": self.memory_read_allowed,
            "memory_write_allowed": self.memory_write_allowed,
            "privacy_epoch": self.privacy_epoch,
            "should_release_voice": self.should_release_voice,
            "started_at": self.started_at,
            "last_activity_at": self.last_activity_at,
            "owner_absent_seconds": round(self.owner_absent_seconds, 3),
        }

"""Typed domain models for person-memory extraction and retrieval."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


MemoryFactCategory = Literal[
    "preference",
    "work_context",
    "goal",
    "recurring_topic",
    "interaction_style",
    "personal_context",
    "correction",
]

PROFILE_SECTIONS = {
    "work_context",
    "interaction_preferences",
    "current_focus",
    "recent_interactions",
    "long_term_context",
}


class MemoryFactCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=500)
    category: MemoryFactCategory
    confidence: float = Field(ge=0.0, le=1.0)
    salience: float = Field(default=0.5, ge=0.0, le=1.0)
    sensitive: bool = False
    source_turn_ids: list[str] = Field(default_factory=list, max_length=32)

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        return " ".join(value.split())


class MemoryExtractionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_updates: dict[str, str] = Field(default_factory=dict)
    new_facts: list[MemoryFactCandidate] = Field(default_factory=list, max_length=50)
    retract_fact_ids: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("profile_updates")
    @classmethod
    def validate_profile_updates(cls, value: dict[str, str]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for key, summary in value.items():
            if key not in PROFILE_SECTIONS:
                raise ValueError(f"unsupported profile section: {key}")
            text = " ".join(str(summary or "").split())[:2000]
            if text:
                normalized[key] = text
        return normalized


@dataclass(frozen=True)
class MemoryJobBatch:
    job_ids: tuple[int, ...]
    person_id: str
    conversation_id: str
    turns: tuple[dict, ...]
    attempts: int


@dataclass(frozen=True)
class DailySummaryCandidate:
    person_id: str
    tenant_id: str
    summary_date: str
    turn_count: int


@dataclass(frozen=True)
class RetrievedPersonMemory:
    person_id: str
    profile: dict[str, str] = field(default_factory=dict)
    facts: tuple[dict, ...] = field(default_factory=tuple)
    summaries: tuple[dict, ...] = field(default_factory=tuple)

    @property
    def empty(self) -> bool:
        return not self.profile and not self.facts and not self.summaries

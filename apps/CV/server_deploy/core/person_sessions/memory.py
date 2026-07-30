"""Compatibility boundary for the durable person-memory repository.

The implementation moved to ``core.person_memory`` so transcript storage,
derived memory, retrieval, and worker jobs share one transactional repository.
"""

from __future__ import annotations

from core.person_memory.repository import (
    PostgresPersonMemoryRepository,
    get_person_memory_repository,
)

__all__ = ["PostgresPersonMemoryRepository", "get_person_memory_repository"]

"""Per-track recognition cache for known people and remembered visitors."""

from __future__ import annotations

import time
from dataclasses import dataclass
import threading

import numpy as np

from config import UNKNOWN_CACHE_EMBEDDING_DELTA, UNKNOWN_CACHE_TTL_SECONDS


@dataclass(frozen=True)
class CachedUnknownVisitor:
    visitor_id: str
    label: str
    similarity: float
    is_returning: bool
    gender: str | None = None


@dataclass
class _CacheEntry:
    kind: str
    similarity: float
    embedding: np.ndarray
    updated_at: float
    name: str | None = None
    visitor_id: str | None = None
    label: str | None = None
    is_returning: bool = False
    gender: str | None = None


class RecognitionCache:
    """Caches recognition results by track_id.

    Known employees are cached for the lifetime of the track. Unknown visitors are
    cached briefly so the same track does not repeatedly run full database and
    persistent visitor matching while the embedding is effectively unchanged.
    """

    def __init__(self):
        self._cache: dict[tuple[str, int], _CacheEntry] = {}
        self._lock = threading.RLock()

    def get_known(
        self, track_id: int, *, scope_key: str = "default"
    ) -> tuple[str | None, float | None]:
        with self._lock:
            entry = self._cache.get((scope_key, track_id))
        if entry is not None and entry.kind == "known":
            return entry.name, entry.similarity
        return None, None

    def get_known_miss(
        self, track_id: int, embedding, *, scope_key: str = "default"
    ) -> float | None:
        with self._lock:
            entry = self._cache.get((scope_key, track_id))
        if entry is None or entry.kind != "known_miss":
            return None
        if time.time() - entry.updated_at > UNKNOWN_CACHE_TTL_SECONDS:
            return None

        current = _normalized(embedding)
        similarity = float(np.dot(entry.embedding, current))
        if 1.0 - similarity > UNKNOWN_CACHE_EMBEDDING_DELTA:
            return None
        return entry.similarity

    def set_known(
        self,
        track_id: int,
        name: str,
        similarity: float,
        embedding,
        *,
        scope_key: str = "default",
    ) -> None:
        with self._lock:
            self._cache[(scope_key, track_id)] = _CacheEntry(
                kind="known",
                name=name,
                similarity=float(similarity),
                embedding=_normalized(embedding),
                updated_at=time.time(),
            )

    def set_known_miss(
        self,
        track_id: int,
        similarity: float,
        embedding,
        *,
        scope_key: str = "default",
    ) -> None:
        with self._lock:
            self._cache[(scope_key, track_id)] = _CacheEntry(
                kind="known_miss",
                similarity=float(similarity),
                embedding=_normalized(embedding),
                updated_at=time.time(),
            )

    def get_unknown(
        self, track_id: int, embedding, *, scope_key: str = "default"
    ) -> CachedUnknownVisitor | None:
        with self._lock:
            entry = self._cache.get((scope_key, track_id))
        if entry is None or entry.kind != "unknown":
            return None
        current = _normalized(embedding)
        similarity = float(np.dot(entry.embedding, current))
        if 1.0 - similarity > UNKNOWN_CACHE_EMBEDDING_DELTA:
            return None

        return CachedUnknownVisitor(
            visitor_id=entry.visitor_id or "",
            label=entry.label or "未知访客",
            similarity=entry.similarity,
            is_returning=entry.is_returning,
            gender=entry.gender,
        )

    def get_cached_unknown(
        self, track_id: int, *, scope_key: str = "default"
    ) -> CachedUnknownVisitor | None:
        with self._lock:
            entry = self._cache.get((scope_key, track_id))
        if entry is None or entry.kind != "unknown":
            return None
        return CachedUnknownVisitor(
            visitor_id=entry.visitor_id or "",
            label=entry.label or "未知访客",
            similarity=entry.similarity,
            is_returning=entry.is_returning,
            gender=entry.gender,
        )

    def set_unknown(
        self,
        track_id: int,
        visitor_id: str,
        label: str,
        similarity: float,
        is_returning: bool,
        gender: str | None,
        embedding,
        *,
        scope_key: str = "default",
    ) -> None:
        with self._lock:
            self._cache[(scope_key, track_id)] = _CacheEntry(
                kind="unknown",
                visitor_id=visitor_id,
                label=label,
                similarity=float(similarity),
                is_returning=is_returning,
                gender=gender,
                embedding=_normalized(embedding),
                updated_at=time.time(),
            )

    def cleanup(
        self,
        active_track_ids: set[int],
        *,
        scope_key: str = "default",
    ) -> None:
        with self._lock:
            for cache_key in list(self._cache.keys()):
                if cache_key[0] == scope_key and cache_key[1] not in active_track_ids:
                    self._cache.pop(cache_key, None)

    def clear_name(self, name: str, tenant_id: str = "") -> None:
        tenant_prefix = f"tenant={tenant_id}|" if tenant_id else ""
        with self._lock:
            for cache_key, entry in list(self._cache.items()):
                if (
                    entry.kind == "known"
                    and entry.name == name
                    and (
                        not tenant_prefix or cache_key[0].startswith(tenant_prefix)
                    )
                ):
                    self._cache.pop(cache_key, None)

    def clear_scope(self, scope_key: str) -> int:
        with self._lock:
            keys = [key for key in self._cache if key[0] == scope_key]
            for key in keys:
                self._cache.pop(key, None)
            return len(keys)

    def clear_known_misses(self, tenant_id: str = "") -> int:
        with self._lock:
            prefix = f"tenant={tenant_id}|" if tenant_id else ""
            keys = [
                key
                for key, entry in self._cache.items()
                if entry.kind == "known_miss"
                and (not prefix or key[0].startswith(prefix))
            ]
            for key in keys:
                self._cache.pop(key, None)
            return len(keys)

    def clear_unknowns(self, tenant_id: str = "") -> int:
        with self._lock:
            prefix = f"tenant={tenant_id}|" if tenant_id else ""
            keys = [
                key
                for key, entry in self._cache.items()
                if entry.kind == "unknown" and (not prefix or key[0].startswith(prefix))
            ]
            for key in keys:
                self._cache.pop(key, None)
            return len(keys)

    def clear_transient(self, tenant_id: str = "") -> int:
        with self._lock:
            prefix = f"tenant={tenant_id}|" if tenant_id else ""
            keys = [
                key
                for key, entry in self._cache.items()
                if entry.kind in {"known_miss", "unknown"}
                and (not prefix or key[0].startswith(prefix))
            ]
            for key in keys:
                self._cache.pop(key, None)
            return len(keys)

    def __len__(self) -> int:
        with self._lock:
            return len(self._cache)


def _normalized(embedding) -> np.ndarray:
    vector = np.asarray(embedding, dtype=np.float32)
    norm = np.linalg.norm(vector)
    if norm > 0:
        vector = vector / norm
    return vector

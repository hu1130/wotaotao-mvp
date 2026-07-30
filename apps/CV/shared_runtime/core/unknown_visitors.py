"""Persistent memory for visitors who are not enrolled employees."""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass

import numpy as np

from config import (
    UNKNOWN_VISITOR_MATCH_THRESHOLD,
    UNKNOWN_VISITOR_RECENT_MATCH_THRESHOLD,
    UNKNOWN_VISITOR_RECENT_SECONDS,
    UNKNOWN_VISITOR_UPDATE_COOLDOWN_SECONDS,
    UNKNOWN_VISITORS_FILE,
    TENANT_ID,
)
from core.tenant import DEFAULT_TENANT_ID, normalize_tenant_id

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UnknownVisitorMatch:
    visitor_id: str
    label: str
    similarity: float
    is_returning: bool
    visit_count: int
    gender: str | None = None


class UnknownVisitorStore:
    """Stores normalized embeddings for unknown visitors across app restarts."""

    CACHE_VERSION = 1

    def __init__(
        self,
        path: str = UNKNOWN_VISITORS_FILE,
        tenant_id: str = TENANT_ID,
    ):
        self.tenant_id = normalize_tenant_id(tenant_id)
        if self.tenant_id == DEFAULT_TENANT_ID:
            self.path = path
        else:
            self.path = os.path.join(
                os.path.dirname(path),
                "tenants",
                self.tenant_id,
                os.path.basename(path),
            )
        self._records: dict[str, dict] = {}
        self._load()

    def match_only(self, embedding) -> UnknownVisitorMatch | None:
        vector = _normalized(embedding)
        visitor_id, similarity = self._best_match(vector)
        if not self._is_match(visitor_id, similarity, time.time()):
            return None
        record = self._records[visitor_id]
        return UnknownVisitorMatch(
            visitor_id=visitor_id,
            label=record["label"],
            similarity=similarity,
            is_returning=True,
            visit_count=int(record.get("visit_count", 1)),
            gender=record.get("gender"),
        )

    def match_or_create(
        self, embedding, gender: str | None = None
    ) -> UnknownVisitorMatch:
        vector = _normalized(embedding)
        now = time.time()
        visitor_id, similarity = self._best_match(vector)
        if self._is_match(visitor_id, similarity, now):
            record = self._records[visitor_id]
            is_returning = True
            if (
                now - float(record.get("last_seen", 0.0))
                >= UNKNOWN_VISITOR_UPDATE_COOLDOWN_SECONDS
            ):
                record["visit_count"] = int(record.get("visit_count", 1)) + 1
                record["embedding"] = _normalized(
                    (np.asarray(record["embedding"], dtype=np.float32) + vector) / 2.0
                )
            if gender and not record.get("gender"):
                record["gender"] = gender
            record["last_seen"] = now
            self._save()
            return UnknownVisitorMatch(
                visitor_id=visitor_id,
                label=record["label"],
                similarity=similarity,
                is_returning=is_returning,
                visit_count=int(record.get("visit_count", 1)),
                gender=record.get("gender") or gender,
            )

        visitor_id = self._next_id()
        label = f"访客{int(visitor_id):03d}"
        self._records[visitor_id] = {
            "label": label,
            "embedding": vector,
            "first_seen": now,
            "last_seen": now,
            "visit_count": 1,
            "gender": gender,
        }
        self._save()
        return UnknownVisitorMatch(
            visitor_id=visitor_id,
            label=label,
            similarity=0.0,
            is_returning=False,
            visit_count=1,
            gender=gender,
        )

    def _best_match(self, vector: np.ndarray) -> tuple[str | None, float]:
        best_id = None
        best_similarity = 0.0
        for visitor_id, record in self._records.items():
            stored = _normalized(record["embedding"])
            similarity = float(np.dot(stored, vector))
            if similarity > best_similarity:
                best_id = visitor_id
                best_similarity = similarity
        return best_id, best_similarity

    def _is_match(self, visitor_id: str | None, similarity: float, now: float) -> bool:
        if visitor_id is None:
            return False
        if similarity >= UNKNOWN_VISITOR_MATCH_THRESHOLD:
            return True

        record = self._records.get(visitor_id)
        if record is None:
            return False
        recent_seconds = now - float(record.get("last_seen", 0.0))
        if (
            0 <= recent_seconds <= UNKNOWN_VISITOR_RECENT_SECONDS
            and similarity >= UNKNOWN_VISITOR_RECENT_MATCH_THRESHOLD
        ):
            logger.info(
                "未知访客短时近似匹配: visitor=%s similarity=%.3f threshold=%.3f recent=%.1fs",
                record.get("label") or visitor_id,
                similarity,
                UNKNOWN_VISITOR_RECENT_MATCH_THRESHOLD,
                recent_seconds,
            )
            return True
        return False

    def _next_id(self) -> str:
        if not self._records:
            return "1"
        return str(max(int(visitor_id) for visitor_id in self._records) + 1)

    def _load(self) -> None:
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError):
            return
        if (
            not isinstance(payload, dict)
            or payload.get("version") != self.CACHE_VERSION
        ):
            return
        records = payload.get("records")
        if not isinstance(records, dict):
            return

        loaded: dict[str, dict] = {}
        for visitor_id, record in records.items():
            if not isinstance(visitor_id, str) or not isinstance(record, dict):
                continue
            if not visitor_id.isdigit():
                continue
            embedding = record.get("embedding")
            if not isinstance(embedding, list):
                continue
            vector = _normalized(embedding)
            if vector.size == 0:
                continue
            try:
                label = str(record.get("label") or f"访客{int(visitor_id):03d}")
                loaded[visitor_id] = {
                    "label": label,
                    "embedding": vector,
                    "first_seen": float(record.get("first_seen", 0.0)),
                    "last_seen": float(record.get("last_seen", 0.0)),
                    "visit_count": max(1, int(record.get("visit_count", 1))),
                    "gender": record.get("gender"),
                }
            except (TypeError, ValueError):
                continue
        self._records = loaded

    def _save(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        records = {}
        for visitor_id, record in self._records.items():
            records[visitor_id] = {
                "label": record.get("label"),
                "embedding": np.asarray(record["embedding"], dtype=np.float32).tolist(),
                "first_seen": float(record.get("first_seen", 0.0)),
                "last_seen": float(record.get("last_seen", 0.0)),
                "visit_count": int(record.get("visit_count", 1)),
                "gender": record.get("gender"),
            }
        payload = {"version": self.CACHE_VERSION, "records": records}
        tmp_path = f"{self.path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp_path, self.path)

    def __len__(self) -> int:
        return len(self._records)


def _normalized(embedding) -> np.ndarray:
    vector = np.asarray(embedding, dtype=np.float32)
    norm = np.linalg.norm(vector)
    if norm > 0:
        vector = vector / norm
    return vector

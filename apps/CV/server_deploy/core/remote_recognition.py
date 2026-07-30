"""API-only recognition path for split client/server deployment."""

from __future__ import annotations

import logging
import select
import threading
import time
from dataclasses import asdict, dataclass, replace
from datetime import date
from typing import Callable

import numpy as np
import psycopg2

from config import (
    ALLOW_REPEAT_CHECKIN,
    AVATAR_SERVER_URL,
    DEVICE_ID,
    TENANT_ID,
    CHECKED_IN_REENTRY_MIN_ABSENT_SECONDS,
    CHECKED_IN_REPEAT_REENTRY_MIN_ABSENT_SECONDS,
    CHECKED_IN_ABSENT_GRACE_SECONDS,
    PERSON_ARRIVAL_TASK_TRIGGER_COOLDOWN_SECONDS,
    CHECKED_IN_STRANGER_SUPPRESS_SECONDS,
    CHECKED_IN_STARE_COOLDOWN_SECONDS,
    CHECKED_IN_STARE_TRIGGER_SECONDS,
    MAX_PROCESS_FACES,
    PG_DATABASE,
    EMBEDDING_SYNC_DEBOUNCE,
    EMBEDDING_SYNC_POLL_INTERVAL,
    IDENTITY_TRAJECTORY_MAX_GAP_SECONDS,
    IDENTITY_TRAJECTORY_MIN_NEAREST_SIMILARITY,
    IDENTITY_TRAJECTORY_RETENTION_SECONDS,
    REPEAT_FEEDBACK_COOLDOWN_SECONDS,
    REMOTE_ENROLLMENT_STRANGER_SUPPRESS_SECONDS,
    RUNTIME_SCOPE_LOCK_SHARDS,
    RUNTIME_SCOPE_IDLE_TTL_SECONDS,
    RUNTIME_SCOPE_MAX_ENTRIES,
    STRANGER_REENTRY_MIN_ABSENT_SECONDS,
    STRANGER_STARE_COOLDOWN_SECONDS,
    STRANGER_STARE_TRIGGER_SECONDS,
)
from core.api_client import ApiClientError, SignedApiClient
from core.attendance_policy import (
    attendance_timezone_name,
    business_now,
    checkout_after_time,
    is_checkout_window,
    should_checkout_checked_in_presence,
)
from core.avatar_event_dispatcher import RemoteAvatarEventDispatcher
from core.concurrency import StripedLock
from core.attendance_db import AttendanceDB
from core.embedding_matcher import EmbeddingMatcher
from core.events import EventBus
from core.face_utils import check_face_quality
from core.gender import gender_salutation
from core.hrms_attendance_sync import get_hrms_attendance_syncer
from core.identity_trajectory import (
    FaceTrajectoryObservation,
    IdentityTrajectoryTracker,
)
from core.person_identity import PersonIdentityRepository
from core.person_memory.repository import get_person_memory_repository
from core.person_sessions.manager import PersonConversationManager
from core.recognition_cache import RecognitionCache
from core.recognition_pipeline import PipelineResult, ProcessedFace
from core.recognizer import FaceRecognizer
from core.runtime_scope import RuntimeScope
from core.tenant import DEFAULT_TENANT_ID, normalize_tenant_id
from core.redis_checkin import RedisCheckIn
from core.tracker import FaceTrackerABC
from core.vector_db import VectorDB
from core.vote import VoteBuffer

logger = logging.getLogger("uvicorn.error")
NOTIFY_CHANNEL = "face_embeddings_changed"


@dataclass
class RemoteCheckedInPresence:
    present: bool = False
    entered_at: float = 0.0
    last_seen_at: float = 0.0
    absent_since: float = 0.0
    last_stare_at: float = 0.0
    stare_triggered: bool = False


@dataclass
class RemoteStrangerPresence:
    present: bool = False
    entered_at: float = 0.0
    last_seen_at: float = 0.0
    absent_since: float = 0.0
    last_stare_at: float = 0.0
    stare_triggered: bool = False
    gender: str | None = None


@dataclass(frozen=True)
class RemoteRecognitionEvidence:
    nearest_name: str = ""
    decision: str = "unknown"


class RemoteRecognitionService:
    """Server-side matcher/check-in service used by device API-only clients."""

    def __init__(self, avatar_url: str = AVATAR_SERVER_URL):
        self.attendance_db = AttendanceDB()
        self.checkin_store = RedisCheckIn()
        self.event_bus = EventBus()
        self.avatar_dispatcher = RemoteAvatarEventDispatcher(avatar_url)
        self.vote_buffer = VoteBuffer()
        self.rec_cache = RecognitionCache()
        self.identity_trajectory = IdentityTrajectoryTracker(
            max_gap_seconds=IDENTITY_TRAJECTORY_MAX_GAP_SECONDS,
            retention_seconds=IDENTITY_TRAJECTORY_RETENTION_SECONDS,
            min_nearest_similarity=IDENTITY_TRAJECTORY_MIN_NEAREST_SIMILARITY,
        )
        self.person_identity = PersonIdentityRepository()
        self._migrated_person_names: set[tuple[str, str]] = set()
        self.vector_db = VectorDB()
        self._tenant_matchers: dict[str, EmbeddingMatcher] = {}
        self._tenant_embeddings: dict[str, list[tuple[str, np.ndarray]]] = {}
        self._tenant_embeddings_by_name: dict[
            str, dict[str, list[tuple[str, np.ndarray]]]
        ] = {}
        self._tenant_vector_counts: dict[str, dict[str, int]] = {}
        self._lock = threading.RLock()
        self._last_embeddings_load: dict[str, float] = {}
        self._scope_locks = StripedLock(RUNTIME_SCOPE_LOCK_SHARDS)
        self._attendance_locks = StripedLock(RUNTIME_SCOPE_LOCK_SHARDS)
        self._identity_locks = StripedLock(RUNTIME_SCOPE_LOCK_SHARDS)
        self._last_stranger_event_at: dict[str, float] = {}
        self._stranger_suppressed_until: dict[str, float] = {}
        self._last_stranger_suppress_log_at: dict[str, float] = {}
        self._last_repeat_feedback: dict[tuple[str, str], float] = {}
        self._checked_in_presence: dict[
            tuple[str, str], RemoteCheckedInPresence
        ] = {}
        self._stranger_presence: dict[tuple[str, str], RemoteStrangerPresence] = {}
        self._last_match_debug_at: dict[str, float] = {}
        self._scope_last_seen: dict[str, float] = {}
        self._last_scope_prune_at = 0.0
        self.reload_embeddings(force=True, tenant_id=DEFAULT_TENANT_ID)
        self._watchdog = RemoteEmbeddingWatchdog(self)
        self._watchdog.start()

    def reload_embeddings(
        self,
        force: bool = False,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> None:
        tenant_id = normalize_tenant_id(tenant_id)
        now = time.time()
        if (
            not force
            and now - self._last_embeddings_load.get(tenant_id, 0.0)
            < EMBEDDING_SYNC_DEBOUNCE
        ):
            return
        embeddings = self.vector_db.get_all_embeddings(tenant_id)
        grouped: dict[str, list[tuple[str, np.ndarray]]] = {}
        for name, embedding in embeddings:
            grouped.setdefault(name, []).append((name, embedding))
        with self._lock:
            self._tenant_embeddings_by_name[tenant_id] = grouped
            self._tenant_vector_counts[tenant_id] = self.vector_db.employee_vector_counts(
                tenant_id
            )
            self._tenant_embeddings[tenant_id] = embeddings
            self._tenant_matchers.setdefault(tenant_id, EmbeddingMatcher([])).update(
                embeddings
            )
            self._last_embeddings_load[tenant_id] = now
        logger.info(
            "远程识别底库已加载: tenant=%s vectors=%d",
            tenant_id,
            len(embeddings),
        )

    def sync_employee_embeddings(
        self, name: str, tenant_id: str = DEFAULT_TENANT_ID
    ) -> None:
        tenant_id = normalize_tenant_id(tenant_id)
        name = (name or "").strip()
        if not name:
            self.reload_embeddings(force=True, tenant_id=tenant_id)
            return
        embeddings = self.vector_db.get_employee_embeddings(name, tenant_id)
        with self._lock:
            self.rec_cache.clear_name(name, tenant_id=tenant_id)
            cleared_transient = self.rec_cache.clear_transient(tenant_id)
            self.vote_buffer.clear_name(name, tenant_id=tenant_id)
            grouped = self._tenant_embeddings_by_name.setdefault(tenant_id, {})
            counts = self._tenant_vector_counts.setdefault(tenant_id, {})
            if embeddings:
                grouped[name] = embeddings
                counts[name] = len(embeddings)
            else:
                grouped.pop(name, None)
                counts.pop(name, None)
            self._rebuild_matcher_locked(tenant_id)
        logger.info(
            "远程识别底库员工已同步: tenant=%s name=%s vectors=%d persons=%d total_vectors=%d",
            tenant_id,
            name,
            len(embeddings),
            len(grouped),
            len(self._tenant_embeddings.get(tenant_id, [])),
        )
        if cleared_transient:
            logger.info("远程识别已清理临时陌生人缓存: name=%s cleared=%d", name, cleared_transient)

    def note_employee_enrolled(
        self,
        name: str,
        reason: str = "employee_enrolled",
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> None:
        """Immediately refresh one employee after enrollment and quiet stale stranger prompts."""

        name = (name or "").strip()
        if not name:
            return
        self._suppress_stranger_events(reason, name, tenant_id)
        tenant_id = normalize_tenant_id(tenant_id)
        self.sync_employee_embeddings(name, tenant_id)
        with self._lock:
            cleared_votes = self.vote_buffer.clear_all(tenant_id)
            cleared_transient = self.rec_cache.clear_transient(tenant_id)
        logger.info(
            "远程识别录入后已刷新: tenant=%s name=%s reason=%s cleared_votes=%d cleared_transient=%d suppress_until=%.1f",
            tenant_id,
            name,
            reason,
            cleared_votes,
            cleared_transient,
            self._stranger_suppressed_until.get(tenant_id, 0.0),
        )

    def _suppress_stranger_events(
        self,
        reason: str,
        name: str | None = None,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> None:
        tenant_id = normalize_tenant_id(tenant_id)
        seconds = max(0.0, REMOTE_ENROLLMENT_STRANGER_SUPPRESS_SECONDS)
        if seconds <= 0:
            return
        until = time.time() + seconds
        with self._lock:
            self._stranger_suppressed_until[tenant_id] = max(
                self._stranger_suppressed_until.get(tenant_id, 0.0), until
            )
        logger.info(
            "远程识别临时抑制陌生人播报: tenant=%s reason=%s name=%s seconds=%.1f",
            tenant_id,
            reason,
            name or "",
            seconds,
        )
        self.avatar_dispatcher.suppress_speech(
            "stranger", seconds, reason, tenant_id=tenant_id
        )

    def sync_changed_snapshot(self, tenant_id: str = DEFAULT_TENANT_ID) -> None:
        tenant_id = normalize_tenant_id(tenant_id)
        current_counts = self.vector_db.employee_vector_counts(tenant_id)
        with self._lock:
            previous_counts = dict(self._tenant_vector_counts.get(tenant_id, {}))
        changed_names = sorted(
            set(previous_counts)
            .union(current_counts)
            .difference(
                name
                for name in set(previous_counts).intersection(current_counts)
                if previous_counts.get(name) == current_counts.get(name)
            )
        )
        if not changed_names:
            return
        logger.info(
            "远程识别底库轮询发现变更: tenant=%s names=%s",
            tenant_id,
            ",".join(changed_names),
        )
        for name in changed_names:
            self.sync_employee_embeddings(name, tenant_id)

    def shutdown(self) -> None:
        self._watchdog.stop()

    def loaded_tenant_ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._tenant_matchers) or (DEFAULT_TENANT_ID,)

    def _rebuild_matcher_locked(self, tenant_id: str) -> None:
        embeddings: list[tuple[str, np.ndarray]] = []
        grouped = self._tenant_embeddings_by_name.setdefault(tenant_id, {})
        for name in sorted(grouped):
            embeddings.extend(grouped[name])
        self._tenant_embeddings[tenant_id] = embeddings
        self._tenant_matchers.setdefault(tenant_id, EmbeddingMatcher([])).update(embeddings)
        self._last_embeddings_load[tenant_id] = time.time()

    def process_frame(self, payload: dict) -> dict:
        scope = RuntimeScope.build(
            str(payload.get("tenant_id") or ""),
            str(payload.get("device_id") or ""),
        )
        self._touch_and_prune_scopes(scope.key)
        with self._scope_locks.for_key(scope.key):
            return self._process_frame_in_scope(payload, scope)

    def _touch_and_prune_scopes(self, current_scope: str) -> None:
        now = time.time()
        with self._lock:
            self._scope_last_seen[current_scope] = now
            if (
                now - self._last_scope_prune_at < 30.0
                and len(self._scope_last_seen) <= RUNTIME_SCOPE_MAX_ENTRIES
            ):
                return
            self._last_scope_prune_at = now
            stale = {
                scope_key
                for scope_key, last_seen in self._scope_last_seen.items()
                if scope_key != current_scope
                and now - last_seen > RUNTIME_SCOPE_IDLE_TTL_SECONDS
            }
            overflow = len(self._scope_last_seen) - len(stale) - RUNTIME_SCOPE_MAX_ENTRIES
            if overflow > 0:
                candidates = sorted(
                    (
                        (last_seen, scope_key)
                        for scope_key, last_seen in self._scope_last_seen.items()
                        if scope_key != current_scope and scope_key not in stale
                    )
                )
                stale.update(scope_key for _, scope_key in candidates[:overflow])
            for scope_key in stale:
                self._scope_last_seen.pop(scope_key, None)
                self._last_stranger_event_at.pop(scope_key, None)
                self._last_stranger_suppress_log_at.pop(scope_key, None)
                self._last_match_debug_at.pop(scope_key, None)
                for key in [key for key in self._last_repeat_feedback if key[0] == scope_key]:
                    self._last_repeat_feedback.pop(key, None)
                for key in [key for key in self._checked_in_presence if key[0] == scope_key]:
                    self._checked_in_presence.pop(key, None)
                for key in [key for key in self._stranger_presence if key[0] == scope_key]:
                    self._stranger_presence.pop(key, None)
        for scope_key in stale:
            cleared = (
                self.vote_buffer.clear_scope(scope_key)
                + self.rec_cache.clear_scope(scope_key)
                + self.identity_trajectory.clear_scope(scope_key)
            )
            logger.info(
                "远程识别空闲运行域已清理: scope=%s entries=%d",
                scope_key,
                cleared,
            )

    def _process_frame_in_scope(self, payload: dict, scope: RuntimeScope) -> dict:
        if scope.tenant_id not in self._tenant_matchers:
            self.reload_embeddings(force=True, tenant_id=scope.tenant_id)
        with self._lock:
            matcher = self._tenant_matchers[scope.tenant_id]
            tenant_embeddings = self._tenant_embeddings.get(scope.tenant_id, [])
        frame_shape = (int(payload["frame_height"]), int(payload["frame_width"]), 3)
        device_id = scope.device_id
        scope_key = scope.key
        active_ids = {int(face["track_id"]) for face in payload.get("faces") or []}
        self.vote_buffer.cleanup_inactive(active_ids, scope_key=scope_key)
        self.rec_cache.cleanup(active_ids, scope_key=scope_key)

        now = time.time()
        selected_faces = self._select_faces(payload.get("faces") or [], frame_shape)
        raw_faces_by_track = {int(face["track_id"]): face for face in selected_faces}
        classified = [
            self._process_face(
                face,
                frame_shape,
                scope_key,
                matcher,
                len(tenant_embeddings),
                scope.tenant_id,
            )
            for face in selected_faces
        ]
        processed_items = [item for item, _ in classified]
        evidences = {
            item.track_id: evidence for item, evidence in classified
        }
        recoveries = self.identity_trajectory.resolve(
            scope_key,
            [
                FaceTrajectoryObservation(
                    track_id=item.track_id,
                    bbox=tuple(item.bbox),
                    recognized_name=(
                        item.name
                        if item.recognized
                        and item.name
                        and evidences[item.track_id].decision in {"accept", "cached"}
                        else ""
                    ),
                    similarity=item.similarity,
                    nearest_name=evidences[item.track_id].nearest_name,
                )
                for item in processed_items
            ],
            now=now,
        )
        recovered_items: list[ProcessedFace] = []
        recovered_track_ids: set[int] = set()
        for item in processed_items:
            recovery = recoveries.get(item.track_id)
            if recovery is None:
                recovered_items.append(item)
                continue
            raw_face = raw_faces_by_track.get(item.track_id) or {}
            embedding = raw_face.get("embedding")
            if embedding:
                self.rec_cache.set_known(
                    item.track_id,
                    recovery.name,
                    recovery.similarity,
                    embedding,
                    scope_key=scope_key,
                )
            recovered = replace(
                item,
                name=recovery.name,
                similarity=recovery.similarity,
                recognized=True,
                label=f"轨迹继承 · {recovery.name}",
                stranger_presence_key=None,
            )
            recovered_items.append(recovered)
            recovered_track_ids.add(item.track_id)
            logger.info(
                "身份轨迹追溯成功: device=%s old_track=%s new_track=%s name=%s age=%.2fs score=%.3f nearest=%s raw_similarity=%.3f",
                device_id,
                recovery.source_track_id,
                recovery.track_id,
                recovery.name,
                recovery.age_seconds,
                recovery.score,
                evidences[item.track_id].nearest_name or "(none)",
                item.similarity,
            )

        processed = []
        checked_in_names = []
        active_checked_in_names: set[str] = set()
        active_stranger_keys: set[str] = set()
        for item in recovered_items:
            if item.recognized and item.name:
                item.person_id = self._stable_person_id(item.name, scope.tenant_id)
            processed.append(asdict(item))
            if item.checked_in_now and item.name:
                checked_in_names.append(item.name)
            if (
                item.recognized
                and item.name
                and self.checkin_store.is_checked_in_today(item.name, scope.tenant_id)
            ):
                checkout_result = self._checkout_checked_in_presence_if_due(
                    scope_key,
                    item.name,
                    now,
                    tenant_id=scope.tenant_id,
                    source="presence_loop",
                )
                if checkout_result.get("checkedOut"):
                    processed[-1]["label"] = f"已签退 · {item.name}"
                    continue
                active_checked_in_names.add(item.name)
                if item.track_id in recovered_track_ids:
                    self._handle_checked_in_presence(
                        scope_key,
                        item.name,
                        now,
                        tenant_id=scope.tenant_id,
                        emit_repeat=False,
                    )
                else:
                    self._handle_checked_in_presence(
                        scope_key,
                        item.name,
                        now,
                        tenant_id=scope.tenant_id,
                    )
            if not item.recognized and item.stranger_presence_key:
                active_stranger_keys.add(item.stranger_presence_key)
                raw_face = raw_faces_by_track.get(item.track_id) or {}
                self._maybe_stranger_event(scope_key, raw_face)
                self._handle_stranger_presence(
                    scope_key,
                    item.stranger_presence_key,
                    now,
                    item.gender,
                )
        self._mark_absent_checked_in_names(scope_key, active_checked_in_names, now)
        self._mark_absent_stranger_keys(scope_key, active_stranger_keys, now)
        return {
            "runtime_scope": scope.to_dict(),
            "faces": processed,
            "face_count": len(payload.get("faces") or []),
            "checked_in_names": checked_in_names,
            "db_person_count": len({name for name, _ in tenant_embeddings}),
            "today_count": self.checkin_store.get_today_count(scope.tenant_id),
        }

    def _stable_person_id(self, name: str, tenant_id: str) -> str:
        tenant_id = normalize_tenant_id(tenant_id)
        person_id = self.person_identity.resolve_person_id(name, tenant_id)
        migration_key = (tenant_id, name)
        with self._identity_locks.for_key(f"{tenant_id}|{name}"):
            if migration_key not in self._migrated_person_names:
                legacy_ids = []
                if tenant_id == DEFAULT_TENANT_ID:
                    legacy_ids.extend(
                        [
                            PersonConversationManager.person_id_for_name(name),
                            f"employee:{person_id.rsplit(':employee:', 1)[-1]}",
                        ]
                    )
                for legacy_person_id in dict.fromkeys(legacy_ids):
                    if legacy_person_id == person_id:
                        continue
                    try:
                        get_person_memory_repository().reassign_person_id(
                            legacy_person_id,
                            person_id,
                        )
                    except Exception:
                        logger.exception(
                            "历史人物记忆身份迁移失败: name=%s old=%s new=%s",
                            name,
                            legacy_person_id,
                            person_id,
                        )
                self._migrated_person_names.add(migration_key)
        return person_id

    @staticmethod
    def _select_faces(faces: list[dict], frame_shape) -> list[dict]:
        if MAX_PROCESS_FACES <= 0 or len(faces) <= MAX_PROCESS_FACES:
            return faces
        frame_h, frame_w = frame_shape[:2]
        frame_cx = frame_w / 2.0
        frame_cy = frame_h / 2.0

        def priority(face: dict) -> tuple[int, float]:
            x1, y1, x2, y2 = face["bbox"]
            area = max(0, x2 - x1) * max(0, y2 - y1)
            cx = (x1 + x2) / 2.0
            cy = (y1 + y2) / 2.0
            return (-area, ((cx - frame_cx) ** 2 + (cy - frame_cy) ** 2) ** 0.5)

        return sorted(faces, key=priority)[:MAX_PROCESS_FACES]

    def _process_face(
        self,
        face: dict,
        frame_shape,
        scope_key: str,
        matcher: EmbeddingMatcher,
        db_vector_count: int,
        tenant_id: str,
    ) -> tuple[ProcessedFace, RemoteRecognitionEvidence]:
        track_id = int(face["track_id"])
        bbox = [int(v) for v in face["bbox"]]
        quality = check_face_quality(face, frame_shape)
        if not quality.passed:
            cached_name, cached_sim = self.rec_cache.get_known(
                track_id, scope_key=scope_key
            )
            if cached_name:
                return (
                    self._complete_known_face(
                        bbox,
                        track_id,
                        cached_name,
                        cached_sim or 0.0,
                        scope_key=scope_key,
                        tenant_id=tenant_id,
                    ),
                    RemoteRecognitionEvidence(cached_name, "cached"),
                )
            return (
                ProcessedFace(
                    bbox=bbox,
                    track_id=track_id,
                    name=None,
                    similarity=0.0,
                    recognized=False,
                    label=quality.label,
                    gender=face.get("gender"),
                ),
                RemoteRecognitionEvidence(),
            )

        embedding = face.get("embedding")
        if not embedding:
            return (
                ProcessedFace(
                    bbox=bbox,
                    track_id=track_id,
                    name=None,
                    similarity=0.0,
                    recognized=False,
                    label="识别中",
                    gender=face.get("gender"),
                ),
                RemoteRecognitionEvidence(),
            )

        vector = np.asarray(embedding, dtype=np.float32)
        cached_name, cached_sim = self.rec_cache.get_known(
            track_id, scope_key=scope_key
        )
        if cached_name is not None:
            return (
                self._complete_known_face(
                    bbox,
                    track_id,
                    cached_name,
                    float(cached_sim or 0.0),
                    scope_key=scope_key,
                    tenant_id=tenant_id,
                ),
                RemoteRecognitionEvidence(cached_name, "cached"),
            )

        known_miss = self.rec_cache.get_known_miss(
            track_id, vector, scope_key=scope_key
        )
        if known_miss is not None:
            return (
                self._unknown_face(bbox, track_id, known_miss, face.get("gender")),
                RemoteRecognitionEvidence(decision="cached_miss"),
            )

        candidate = matcher.match_candidate(vector)
        similarity = float(candidate.similarity or 0.0)
        self._maybe_log_match_candidate(
            scope_key,
            track_id,
            candidate.name,
            similarity,
            candidate.decision,
            db_vector_count,
        )
        if candidate.decision == "reject":
            self.rec_cache.set_known_miss(
                track_id, similarity, vector, scope_key=scope_key
            )
            return (
                self._unknown_face(bbox, track_id, similarity, face.get("gender")),
                RemoteRecognitionEvidence(
                    nearest_name=candidate.nearest_name or "",
                    decision=candidate.decision,
                ),
            )

        if not face.get("fresh_detection", True):
            return (
                ProcessedFace(
                    bbox=bbox,
                    track_id=track_id,
                    name=candidate.name,
                    similarity=similarity,
                    recognized=True,
                    label=f"确认中 · {candidate.name}",
                    gender=face.get("gender"),
                ),
                RemoteRecognitionEvidence(
                    nearest_name=candidate.nearest_name or candidate.name or "",
                    decision=candidate.decision,
                ),
            )

        voted_name = self.vote_buffer.vote(
            track_id,
            candidate.name,
            similarity,
            time.time(),
            scope_key=scope_key,
        )
        if voted_name is None:
            return (
                ProcessedFace(
                    bbox=bbox,
                    track_id=track_id,
                    name=candidate.name,
                    similarity=similarity,
                    recognized=True,
                    label=f"确认中 · {candidate.name}",
                    gender=face.get("gender"),
                ),
                RemoteRecognitionEvidence(
                    nearest_name=candidate.nearest_name or candidate.name or "",
                    decision=candidate.decision,
                ),
            )

        self.rec_cache.set_known(
            track_id, voted_name, similarity, vector, scope_key=scope_key
        )
        return (
            self._complete_known_face(
                bbox,
                track_id,
                voted_name,
                similarity,
                scope_key=scope_key,
                tenant_id=tenant_id,
            ),
            RemoteRecognitionEvidence(
                nearest_name=candidate.nearest_name or voted_name,
                decision=candidate.decision,
            ),
        )

    def _maybe_log_match_candidate(
        self,
        scope_key: str,
        track_id: int,
        name: str | None,
        similarity: float,
        decision: str,
        db_vector_count: int,
    ) -> None:
        now = time.time()
        if now - self._last_match_debug_at.get(scope_key, 0.0) < 5.0:
            return
        self._last_match_debug_at[scope_key] = now
        logger.info(
            "远程识别候选: scope=%s track=%s name=%s similarity=%.3f decision=%s db_vectors=%d",
            scope_key,
            track_id,
            name or "(none)",
            similarity,
            decision,
            db_vector_count,
        )

    def _complete_known_face(
        self,
        bbox: list[int],
        track_id: int,
        name: str,
        similarity: float,
        *,
        scope_key: str,
        tenant_id: str,
    ) -> ProcessedFace:
        with self._attendance_locks.for_key(f"{tenant_id}|{name}"):
            return self._complete_known_face_locked(
                bbox,
                track_id,
                name,
                similarity,
                scope_key=scope_key,
                tenant_id=tenant_id,
            )

    def _complete_known_face_locked(
        self,
        bbox: list[int],
        track_id: int,
        name: str,
        similarity: float,
        *,
        scope_key: str,
        tenant_id: str,
    ) -> ProcessedFace:
        if not ALLOW_REPEAT_CHECKIN and self.checkin_store.is_checked_out_today(
            name, tenant_id
        ):
            return self._known_face(bbox, track_id, name, similarity, tenant_id)
        if not ALLOW_REPEAT_CHECKIN and self.checkin_store.is_checked_in_today(
            name, tenant_id
        ):
            now = time.time()
            checkout_result = self._checkout_checked_in_presence_if_due_locked(
                scope_key,
                name,
                now,
                tenant_id=tenant_id,
                source="known_face",
            )
            if checkout_result.get("checkedOut"):
                return self._known_face(bbox, track_id, name, similarity, tenant_id)
            self._handle_checked_in_presence(
                scope_key,
                name,
                now,
                tenant_id=tenant_id,
            )
            return self._known_face(bbox, track_id, name, similarity, tenant_id)
        try:
            is_first = not self.attendance_db.has_any_record(name, tenant_id)
            is_returning = not is_first and not self.attendance_db.has_record_today(
                name, tenant_id
            )
            row_id = self.attendance_db.check_in(name, tenant_id)
            self.checkin_store.mark_checked_in(name, tenant_id)
            self._mark_checked_in_present(scope_key, name, time.time())
            get_hrms_attendance_syncer().enqueue_check_in(
                self.attendance_db,
                tenant_id=tenant_id,
                name=name,
                row_id=row_id,
            )
            self.event_bus.publish(
                "checkin",
                {
                    "name": name,
                    "tenant_id": tenant_id,
                    "row_id": row_id,
                    "similarity": round(similarity, 4),
                    "time": time.time(),
                    "runtime_scope": scope_key,
                },
            )
            self._emit_avatar_event(
                "check_in",
                {
                    "name": name,
                    "tenant_id": tenant_id,
                    "is_first": is_first,
                    "is_returning": is_returning,
                    "runtime_scope": scope_key,
                },
            )
            logger.info("远程签到成功: %s sim=%.3f row=%s", name, similarity, row_id)
            checked_in_now = True
        except Exception as exc:
            logger.warning("远程签到失败: %s %s", name, exc)
            checked_in_now = False
        return ProcessedFace(
            bbox=bbox,
            track_id=track_id,
            name=name,
            similarity=similarity,
            recognized=True,
            label=f"已签到 · {name}",
            checked_in_now=checked_in_now,
        )

    def _known_face(
        self,
        bbox: list[int],
        track_id: int,
        name: str,
        similarity: float,
        tenant_id: str,
    ) -> ProcessedFace:
        if self.checkin_store.is_checked_out_today(name, tenant_id):
            label = f"已签退 · {name}"
        elif self.checkin_store.is_checked_in_today(name, tenant_id):
            label = f"已签到 · {name}"
        else:
            label = name
        return ProcessedFace(
            bbox=bbox,
            track_id=track_id,
            name=name,
            similarity=similarity,
            recognized=True,
            label=label,
        )

    @staticmethod
    def _unknown_face(
        bbox: list[int],
        track_id: int,
        similarity: float,
        gender: str | None,
    ) -> ProcessedFace:
        return ProcessedFace(
            bbox=bbox,
            track_id=track_id,
            name=None,
            similarity=similarity,
            recognized=False,
            label="未知访客",
            gender=gender,
            stranger_presence_key=f"track:{track_id}",
        )

    def _maybe_stranger_event(self, scope_key: str, face: dict) -> None:
        now = time.time()
        tenant_id = self._tenant_from_scope_key(scope_key)
        with self._lock:
            suppressed_until = self._stranger_suppressed_until.get(tenant_id, 0.0)
        if now < suppressed_until:
            if now - self._last_stranger_suppress_log_at.get(scope_key, 0.0) >= 2.0:
                self._last_stranger_suppress_log_at[scope_key] = now
                logger.info(
                    "远程识别跳过陌生人播报: reason=enrollment_sync_window remaining=%.1fs",
                    suppressed_until - now,
                )
            return
        if self._has_recent_checked_in_presence(scope_key, now):
            logger.info(
                "远程识别跳过陌生人播报: reason=checked_in_present window=%.1fs",
                CHECKED_IN_STRANGER_SUPPRESS_SECONDS,
            )
            return
        last_event_at = self._last_stranger_event_at.get(scope_key, 0.0)
        if now - last_event_at < 30.0:
            return
        self._last_stranger_event_at[scope_key] = now
        payload = {
            "runtime_scope": scope_key,
            "visitor_label": "未知访客",
            "is_returning": False,
            "gender": face.get("gender"),
            "time": now,
        }
        self.event_bus.publish("stranger_detected", payload)
        self._emit_avatar_event("stranger", payload)

    def _handle_stranger_presence(
        self,
        scope_key: str,
        presence_key: str,
        now: float,
        gender: str | None,
    ) -> None:
        if not presence_key:
            return
        scoped_key = (scope_key, presence_key)
        state = self._stranger_presence.get(scoped_key)
        if state is None:
            self._stranger_presence[scoped_key] = RemoteStrangerPresence(
                present=True,
                entered_at=now,
                last_seen_at=now,
                gender=gender,
            )
            logger.info("远程陌生人在场状态初始化: key=%s", presence_key)
            return

        if not state.present:
            brief_absent = (
                state.absent_since > 0
                and now - state.absent_since < STRANGER_REENTRY_MIN_ABSENT_SECONDS
            )
            state.present = True
            state.entered_at = now
            state.last_stare_at = 0.0
            state.stare_triggered = False
            logger.info(
                "远程陌生人重新入场: key=%s brief=%s absent=%.1fs",
                presence_key,
                brief_absent,
                now - state.absent_since if state.absent_since else 0.0,
            )

        state.gender = gender or state.gender
        state.entered_at = state.entered_at or now
        state.last_seen_at = now
        state.absent_since = 0.0
        self._maybe_stranger_stare_event(scope_key, presence_key, state, now)

    def _maybe_stranger_stare_event(
        self,
        scope_key: str,
        presence_key: str,
        state: RemoteStrangerPresence,
        now: float,
    ) -> None:
        tenant_id = self._tenant_from_scope_key(scope_key)
        with self._lock:
            suppressed_until = self._stranger_suppressed_until.get(tenant_id, 0.0)
        if now < suppressed_until:
            if now - self._last_stranger_suppress_log_at.get(scope_key, 0.0) >= 2.0:
                self._last_stranger_suppress_log_at[scope_key] = now
                logger.info(
                    "远程 stranger_stare 跳过: reason=enrollment_sync_window remaining=%.1fs",
                    suppressed_until - now,
                )
            return
        if self._has_recent_checked_in_presence(scope_key, now):
            if now - self._last_stranger_suppress_log_at.get(scope_key, 0.0) >= 2.0:
                self._last_stranger_suppress_log_at[scope_key] = now
                logger.info(
                    "远程 stranger_stare 跳过: reason=checked_in_present window=%.1fs",
                    CHECKED_IN_STRANGER_SUPPRESS_SECONDS,
                )
            return

        dwell_seconds = now - (state.entered_at or now)
        if dwell_seconds < STRANGER_STARE_TRIGGER_SECONDS:
            return
        if state.stare_triggered:
            return
        if (
            state.last_stare_at > 0
            and now - state.last_stare_at < STRANGER_STARE_COOLDOWN_SECONDS
        ):
            return

        payload = {
            "runtime_scope": scope_key,
            "time": now,
            "salutation": gender_salutation(state.gender),
        }
        self.event_bus.publish("stranger_stare", payload)
        self._emit_avatar_event("stranger_stare", payload)
        state.last_stare_at = now
        state.stare_triggered = True
        logger.info(
            "远程 stranger_stare 已触发: key=%s dwell=%.1fs cooldown=%.1fs once_per_presence=true",
            presence_key,
            dwell_seconds,
            STRANGER_STARE_COOLDOWN_SECONDS,
        )

    def _maybe_repeat_event(self, scope_key: str, name: str) -> None:
        now = time.time()
        feedback_key = (scope_key, name)
        last = self._last_repeat_feedback.get(feedback_key, 0.0)
        if now - last < REPEAT_FEEDBACK_COOLDOWN_SECONDS:
            logger.info(
                "远程 repeat 跳过冷却: name=%s remaining=%.1fs",
                name,
                REPEAT_FEEDBACK_COOLDOWN_SECONDS - (now - last),
            )
            return
        self._last_repeat_feedback[feedback_key] = now
        self.event_bus.publish(
            "repeat_checkin",
            {"name": name, "time": now, "runtime_scope": scope_key},
        )
        self._emit_avatar_event(
            "repeat", {"name": name, "runtime_scope": scope_key}
        )
        logger.info("远程 repeat 已触发: name=%s", name)

    def _maybe_arrival_task_or_repeat_event(
        self,
        scope_key: str,
        name: str,
        *,
        tenant_id: str = "",
    ) -> None:
        tenant_id = normalize_tenant_id(tenant_id or self._tenant_from_scope_key(scope_key))
        target_person_id = self._stable_person_id(name, tenant_id)
        try:
            has_arrival_task = get_person_memory_repository().has_active_arrival_task(
                tenant_id=tenant_id,
                target_person_id=target_person_id,
            )
        except Exception:
            logger.exception(
                "人物到场任务状态检查失败，回退 repeat: tenant=%s name=%s",
                tenant_id,
                name,
            )
            has_arrival_task = False
        if not has_arrival_task:
            self._maybe_repeat_event(scope_key, name)
            return

        result = self._maybe_arrival_tasks(
            scope_key,
            name,
            tenant_id=tenant_id,
            target_person_id=target_person_id,
            reason="repeat_reentry",
        )
        logger.info(
            "人物到场任务覆盖 repeat: tenant=%s name=%s claimed=%d sent=%d",
            tenant_id,
            name,
            result.get("claimed", 0),
            result.get("sent", 0),
        )

    def _maybe_arrival_tasks(
        self,
        scope_key: str,
        name: str,
        *,
        tenant_id: str = "",
        reason: str = "",
        target_person_id: str = "",
    ) -> dict:
        tenant_id = normalize_tenant_id(tenant_id or self._tenant_from_scope_key(scope_key))
        try:
            target_person_id = target_person_id or self._stable_person_id(name, tenant_id)
            tasks = get_person_memory_repository().claim_arrival_tasks(
                tenant_id=tenant_id,
                target_person_id=target_person_id,
                cooldown_seconds=PERSON_ARRIVAL_TASK_TRIGGER_COOLDOWN_SECONDS,
                limit=5,
            )
        except Exception:
            logger.exception(
                "人物到场任务读取失败: tenant=%s name=%s reason=%s",
                tenant_id,
                name,
                reason,
            )
            return {"claimed": 0, "sent": 0}
        if not tasks:
            logger.debug(
                "人物到场任务未命中: tenant=%s name=%s reason=%s",
                tenant_id,
                name,
                reason,
            )
            return {"claimed": 0, "sent": 0}

        sent = 0
        for task in tasks:
            text = self._arrival_task_speech_text(task, fallback_target_name=name)
            if not text:
                continue
            result = self.avatar_dispatcher.emit_custom_speech(
                text=text,
                tenant_id=tenant_id,
                event_type="arrival_task",
                name=name,
                priority=88,
                source="person_arrival_task",
                dedup_key=f"{tenant_id}:arrival_task:{task.get('taskId')}",
            )
            sent += int(result.speech_sent)
            logger.info(
                "人物到场任务已触发: tenant=%s name=%s task=%s repeat=%s exact=%s speech=%s reason=%s cooldown=%.1fs",
                tenant_id,
                name,
                task.get("taskId"),
                task.get("repeat"),
                task.get("exactText"),
                result.speech_sent,
                reason,
                PERSON_ARRIVAL_TASK_TRIGGER_COOLDOWN_SECONDS,
            )
        logger.info(
            "人物到场任务触发完成: tenant=%s name=%s tasks=%d sent=%d reason=%s",
            tenant_id,
            name,
            len(tasks),
            sent,
            reason,
        )
        return {"claimed": len(tasks), "sent": sent}

    @staticmethod
    def _arrival_task_speech_text(
        task: dict,
        *,
        fallback_target_name: str = "",
    ) -> str:
        content = " ".join(str(task.get("content") or "").split())[:220]
        if not content:
            return ""
        if bool(task.get("exactText")):
            return content
        creator_name = str(task.get("creatorName") or "").strip() or "有人"
        creator_person_id = str(task.get("creatorPersonId") or "").strip()
        target_person_id = str(task.get("targetPersonId") or "").strip()
        target_name = (
            str(task.get("targetName") or "").strip()
            or fallback_target_name.strip()
            or "你"
        )
        if creator_person_id and target_person_id and creator_person_id == target_person_id:
            return f"{target_name}，{content}"
        if creator_name and creator_name == target_name:
            return f"{target_name}，{content}"
        return f"{target_name}，{creator_name}让我提醒你：{content}"

    def _maybe_checked_in_stare_event(
        self,
        scope_key: str,
        name: str,
        state: RemoteCheckedInPresence,
        now: float,
    ) -> None:
        entered_at = state.entered_at or now
        dwell_seconds = now - entered_at
        if dwell_seconds < CHECKED_IN_STARE_TRIGGER_SECONDS:
            return
        if state.stare_triggered:
            return
        if (
            state.last_stare_at > 0
            and now - state.last_stare_at < CHECKED_IN_STARE_COOLDOWN_SECONDS
        ):
            return

        payload = {"name": name, "time": now, "runtime_scope": scope_key}
        self.event_bus.publish("checked_in_stare", payload)
        self._emit_avatar_event("checked_in_stare", payload)
        state.last_stare_at = now
        state.stare_triggered = True
        logger.info(
            "远程 checked_in_stare 已触发: name=%s dwell=%.1fs cooldown=%.1fs once_per_presence=true",
            name,
            dwell_seconds,
            CHECKED_IN_STARE_COOLDOWN_SECONDS,
        )

    def _handle_checked_in_presence(
        self,
        scope_key: str,
        name: str,
        now: float,
        *,
        tenant_id: str = "",
        emit_repeat: bool = True,
    ) -> None:
        tenant_id = normalize_tenant_id(tenant_id or self._tenant_from_scope_key(scope_key))
        presence_key = (scope_key, name)
        state = self._checked_in_presence.get(presence_key)
        if state is None:
            state = RemoteCheckedInPresence(
                present=True,
                entered_at=now,
                last_seen_at=now,
            )
            self._checked_in_presence[presence_key] = state
            if emit_repeat:
                logger.info(
                    "远程已签到首次在场按重新入场触发: name=%s scope=%s",
                    name,
                    scope_key,
                )
                self._maybe_arrival_task_or_repeat_event(
                    scope_key,
                    name,
                    tenant_id=tenant_id,
                )
                state.last_stare_at = 0.0
                state.stare_triggered = False
            else:
                logger.info("远程已签到在场状态初始化: name=%s", name)
                return

        was_absent = not state.present and state.absent_since > 0
        absent_seconds = now - state.absent_since if was_absent else 0.0
        if was_absent:
            state.entered_at = now
            state.last_stare_at = 0.0
            state.stare_triggered = False
        if (
            emit_repeat
            and was_absent
            and absent_seconds >= CHECKED_IN_REPEAT_REENTRY_MIN_ABSENT_SECONDS
        ):
            logger.info(
                "远程已签到重新入场: name=%s absent=%.1fs threshold=%.1fs",
                name,
                absent_seconds,
                CHECKED_IN_REPEAT_REENTRY_MIN_ABSENT_SECONDS,
            )
            self._maybe_arrival_task_or_repeat_event(
                scope_key,
                name,
                tenant_id=tenant_id,
            )
        elif emit_repeat and was_absent:
            logger.info(
                "远程已签到短暂离场忽略: name=%s absent=%.1fs threshold=%.1fs",
                name,
                absent_seconds,
                CHECKED_IN_REPEAT_REENTRY_MIN_ABSENT_SECONDS,
            )

        state.present = True
        state.entered_at = state.entered_at or now
        state.last_seen_at = now
        state.absent_since = 0.0
        self._maybe_checked_in_stare_event(scope_key, name, state, now)

    def _mark_checked_in_present(self, scope_key: str, name: str, now: float) -> None:
        state = self._checked_in_presence.setdefault(
            (scope_key, name), RemoteCheckedInPresence()
        )
        was_absent = not state.present
        state.present = True
        if was_absent:
            state.entered_at = now
            state.last_stare_at = 0.0
            state.stare_triggered = False
        else:
            state.entered_at = state.entered_at or now
        state.last_seen_at = now
        state.absent_since = 0.0

    def _checkout_checked_in_presence_if_due(
        self,
        scope_key: str,
        name: str,
        now: float,
        *,
        tenant_id: str,
        source: str,
    ) -> dict:
        with self._attendance_locks.for_key(f"{tenant_id}|{name}"):
            return self._checkout_checked_in_presence_if_due_locked(
                scope_key,
                name,
                now,
                tenant_id=tenant_id,
                source=source,
            )

    def _checkout_checked_in_presence_if_due_locked(
        self,
        scope_key: str,
        name: str,
        now: float,
        *,
        tenant_id: str,
        source: str,
    ) -> dict:
        if not self._should_checkout_on_presence(scope_key, name, now):
            return {"checkedOut": False, "reason": "not_due"}
        checkout_result = self.checkout(name, tenant_id)
        if checkout_result.get("checkedOut"):
            self._checked_in_presence.pop((scope_key, name), None)
            logger.info(
                "远程18点后识别触发签退: scope=%s tenant=%s name=%s duration=%s source=%s",
                scope_key,
                tenant_id,
                name,
                checkout_result.get("durationMinutes"),
                source,
            )
            return checkout_result
        logger.warning(
            "远程18点后签退未落库: scope=%s tenant=%s name=%s reason=%s source=%s",
            scope_key,
            tenant_id,
            name,
            checkout_result.get("reason"),
            source,
        )
        return checkout_result

    def _should_checkout_on_presence(
        self,
        scope_key: str,
        name: str,
        now: float,
    ) -> bool:
        state = self._checked_in_presence.get((scope_key, name))
        decision = should_checkout_checked_in_presence(
            state,
            now_seconds=now,
            min_absent_seconds=CHECKED_IN_REENTRY_MIN_ABSENT_SECONDS,
        )
        if not decision and (state is None or not bool(getattr(state, "present", False))):
            current = business_now()
            absent_since = float(getattr(state, "absent_since", 0.0) or 0.0)
            absent_seconds = now - absent_since if absent_since > 0 else 0.0
            logger.info(
                "远程签退判定未触发: scope=%s name=%s timezone=%s business_now=%s "
                "checkout_after=%s checkout_window=%s present=%s absent=%.1fs "
                "min_absent=%.1fs",
                scope_key,
                name,
                attendance_timezone_name(),
                current.isoformat(),
                checkout_after_time(),
                is_checkout_window(current),
                bool(getattr(state, "present", False)) if state is not None else None,
                absent_seconds,
                CHECKED_IN_REENTRY_MIN_ABSENT_SECONDS,
            )
        return decision

    def _has_recent_checked_in_presence(self, scope_key: str, now: float) -> bool:
        window = max(0.0, CHECKED_IN_STRANGER_SUPPRESS_SECONDS)
        if window <= 0:
            return False
        for (candidate_scope, _), state in self._checked_in_presence.items():
            if candidate_scope != scope_key:
                continue
            if state.present:
                return True
            if state.last_seen_at and now - state.last_seen_at <= window:
                return True
        return False

    def _mark_absent_checked_in_names(
        self, scope_key: str, active_names: set[str], now: float
    ) -> None:
        for (candidate_scope, name), state in list(self._checked_in_presence.items()):
            if candidate_scope != scope_key:
                continue
            if name in active_names:
                continue
            if state.present:
                last_seen_at = state.last_seen_at or now
                missing_seconds = now - last_seen_at
                if missing_seconds < CHECKED_IN_ABSENT_GRACE_SECONDS:
                    logger.debug(
                        "远程已签到暂未确认离场: name=%s missing=%.1fs grace=%.1fs",
                        name,
                        missing_seconds,
                        CHECKED_IN_ABSENT_GRACE_SECONDS,
                    )
                    continue
                state.present = False
                state.absent_since = last_seen_at
                state.entered_at = 0.0
                state.last_stare_at = 0.0
                state.stare_triggered = False
                logger.info(
                    "远程已签到离场: name=%s missing=%.1fs grace=%.1fs",
                    name,
                    missing_seconds,
                    CHECKED_IN_ABSENT_GRACE_SECONDS,
                )

    def _mark_absent_stranger_keys(
        self, scope_key: str, active_keys: set[str], now: float
    ) -> None:
        for (candidate_scope, key), state in list(self._stranger_presence.items()):
            if candidate_scope != scope_key:
                continue
            if key in active_keys:
                continue
            if state.present:
                state.present = False
                state.absent_since = now
                state.entered_at = 0.0
                state.last_stare_at = 0.0
                state.stare_triggered = False
                logger.info("远程陌生人离场: key=%s", key)

    def checkout(self, name: str, tenant_id: str = DEFAULT_TENANT_ID) -> dict:
        tenant_id = normalize_tenant_id(tenant_id)
        duration = self.attendance_db.check_out(name, tenant_id)
        if duration is None:
            return {"checkedOut": False, "reason": "no open check-in record"}
        self.checkin_store.reset_checkin(name, tenant_id)
        get_hrms_attendance_syncer().enqueue_check_out(
            self.attendance_db,
            tenant_id=tenant_id,
            name=name,
        )
        self.event_bus.publish(
            "checkout",
            {
                "tenant_id": tenant_id,
                "name": name,
                "duration_minutes": duration,
                "time": time.time(),
            },
        )
        self._emit_avatar_event("check_out", {"tenant_id": tenant_id, "name": name})
        return {"checkedOut": True, "durationMinutes": duration}

    def _emit_avatar_event(self, event_type: str, payload: dict) -> None:
        payload = dict(payload or {})
        if not payload.get("tenant_id"):
            payload["tenant_id"] = self._tenant_from_scope_key(
                str(payload.get("runtime_scope") or "")
            )
        result = self.avatar_dispatcher.emit(event_type, payload)
        logger.info(
            "远程识别规范事件已提交: type=%s action=%s speech=%s speech_type=%s reason=%s",
            event_type,
            result.action_sent,
            result.speech_sent,
            result.speech_type,
            result.reason,
        )

    @staticmethod
    def _tenant_from_scope_key(scope_key: str) -> str:
        prefix = "tenant="
        if scope_key.startswith(prefix):
            return normalize_tenant_id(scope_key[len(prefix) :].split("|", 1)[0])
        return DEFAULT_TENANT_ID


class RemoteEmbeddingWatchdog(threading.Thread):
    """Keeps server-side remote recognition embeddings synced with pgvector."""

    def __init__(self, service: RemoteRecognitionService):
        super().__init__(name="RemoteEmbeddingWatchdog", daemon=True)
        self.service = service
        self._stop_event = threading.Event()
        self._refresh_requested = threading.Event()
        self._pending_names: set[tuple[str, str]] = set()
        self._lock = threading.RLock()

    def stop(self) -> None:
        self._stop_event.set()
        self._refresh_requested.set()
        self.join(timeout=5)

    def request_employee_refresh(
        self, name: str, tenant_id: str = DEFAULT_TENANT_ID
    ) -> None:
        tenant_id = normalize_tenant_id(tenant_id)
        name = (name or "").strip()
        with self._lock:
            if name:
                self._pending_names.add((tenant_id, name))
        self._refresh_requested.set()

    def run(self) -> None:
        listener = threading.Thread(
            target=self._listen_loop,
            name="RemoteEmbeddingNotifyListener",
            daemon=True,
        )
        listener.start()
        self._poll_loop()

    def _listen_loop(self) -> None:
        while not self._stop_event.is_set():
            conn = None
            try:
                conn = psycopg2.connect(**VectorDB._connect_kwargs(PG_DATABASE))
                conn.autocommit = True
                with conn.cursor() as cur:
                    cur.execute(f"LISTEN {NOTIFY_CHANNEL};")
                logger.info("远程识别底库看门狗 LISTEN 已启动: channel=%s", NOTIFY_CHANNEL)
                while not self._stop_event.is_set():
                    try:
                        readable, _, _ = select.select([conn], [], [], 1.0)
                    except (OSError, ValueError):
                        break
                    if not readable:
                        continue
                    conn.poll()
                    while conn.notifies:
                        notify = conn.notifies.pop(0)
                        payload = (notify.payload or "").strip()
                        tenant_id, separator, name = payload.partition("|")
                        if not separator:
                            tenant_id, name = DEFAULT_TENANT_ID, payload
                        logger.info(
                            "远程识别底库收到变更通知: channel=%s tenant=%s name=%s",
                            notify.channel,
                            tenant_id,
                            name or "(unknown)",
                        )
                        if name:
                            self.request_employee_refresh(name, tenant_id)
                        else:
                            self.service.reload_embeddings(
                                force=True, tenant_id=tenant_id
                            )
            except Exception as exc:
                logger.warning("远程识别底库 LISTEN 异常，5 秒后重连: %s", exc)
            finally:
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass
            if not self._stop_event.is_set():
                self._stop_event.wait(5.0)

    def _poll_loop(self) -> None:
        last_poll_at = time.time()
        while not self._stop_event.is_set():
            timeout = min(1.0, max(1.0, EMBEDDING_SYNC_POLL_INTERVAL))
            signaled = self._refresh_requested.wait(timeout=timeout)
            if self._stop_event.is_set():
                break
            if signaled:
                self._refresh_requested.clear()
                self._flush_pending_names()
                last_poll_at = time.time()
                continue
            if time.time() - last_poll_at >= EMBEDDING_SYNC_POLL_INTERVAL:
                try:
                    for tenant_id in self.service.loaded_tenant_ids():
                        self.service.sync_changed_snapshot(tenant_id)
                except Exception as exc:
                    logger.warning("远程识别底库轮询检查失败: %s", exc)
                last_poll_at = time.time()

    def _flush_pending_names(self) -> None:
        with self._lock:
            names = sorted(self._pending_names)
            self._pending_names.clear()
        if not names:
            return
        time.sleep(max(0.0, EMBEDDING_SYNC_DEBOUNCE))
        for tenant_id, name in names:
            try:
                self.service.sync_employee_embeddings(name, tenant_id)
            except Exception as exc:
                logger.warning(
                    "远程识别底库员工同步失败: tenant=%s name=%s error=%s",
                    tenant_id,
                    name,
                    exc,
                )


class RemoteCheckInStore:
    """Device-side check-in state facade backed by FastAPI."""

    def __init__(
        self,
        client: SignedApiClient | None = None,
        today_provider: Callable[[], str] | None = None,
    ):
        self.client = client or SignedApiClient()
        self._today_provider = today_provider or (lambda: date.today().isoformat())
        self._local_date = self._today()
        self._checked_in: set[str] = set()
        self._checked_out: set[str] = set()
        self._today_count = 0

    def update_from_frame(self, data: dict) -> None:
        self._reset_local_if_new_day()
        self._today_count = max(self._today_count, int(data.get("today_count") or 0))
        for name in data.get("checked_in_names") or []:
            self._checked_in.add(name)
            self._checked_out.discard(name)

    def is_checked_in_today(self, name: str) -> bool:
        self._reset_local_if_new_day()
        if name in self._checked_in:
            return True
        self._refresh_name(name)
        return name in self._checked_in

    def is_checked_out_today(self, name: str) -> bool:
        self._reset_local_if_new_day()
        if name in self._checked_out:
            return True
        self._refresh_name(name)
        return name in self._checked_out

    def get_today_count(self) -> int:
        self._reset_local_if_new_day()
        return self._today_count

    def mark_checked_out(self, name: str) -> None:
        self._reset_local_if_new_day()
        self._checked_in.discard(name)
        self._checked_out.add(name)

    def _refresh_name(self, name: str) -> None:
        self._reset_local_if_new_day()
        try:
            data = self.client.get(f"/api/v1/attendance/today/{_quote_path(name)}", timeout=3)
            records = (data.get("data") or {}).get("records") or []
        except Exception as exc:
            logger.debug("远程签到状态读取失败: %s %s", name, exc)
            return
        if any(item.get("check_out") for item in records):
            self._checked_out.add(name)
        else:
            self._checked_out.discard(name)
        if any(not item.get("check_out") for item in records):
            self._checked_in.add(name)
        else:
            self._checked_in.discard(name)

    def _today(self) -> str:
        return self._today_provider()

    def _reset_local_if_new_day(self) -> None:
        today = self._today()
        if self._local_date == today:
            return
        logger.info(
            "远程签到客户端缓存跨天清理: previous=%s current=%s checked_in=%d checked_out=%d today_count=%d",
            self._local_date,
            today,
            len(self._checked_in),
            len(self._checked_out),
            self._today_count,
        )
        self._local_date = today
        self._checked_in.clear()
        self._checked_out.clear()
        self._today_count = 0


class RemoteRecognitionPipeline:
    """Device-side pipeline that sends local embeddings to the server API."""

    def __init__(
        self,
        recognizer: FaceRecognizer,
        tracker: FaceTrackerABC,
        checkin_store: RemoteCheckInStore,
        client: SignedApiClient | None = None,
    ):
        self.recognizer = recognizer
        self.tracker = tracker
        self.checkin_store = checkin_store
        self.client = client or SignedApiClient()
        self.db_embeddings: list = []
        self._last_db_person_count = 0

    def process_frame(self, frame) -> PipelineResult:
        faces = self.tracker.update(frame, self.recognizer)
        h, w = frame.shape[:2]
        payload = {
            "tenant_id": TENANT_ID,
            "device_id": DEVICE_ID,
            "frame_width": int(w),
            "frame_height": int(h),
            "faces": [self._face_payload(face) for face in faces],
        }
        try:
            response = self.client.post(
                "/api/v1/recognition/frame",
                payload,
                timeout=8,
            )
            data = response.get("data") or {}
        except ApiClientError as exc:
            logger.warning("远程识别 API 调用失败: %s", exc)
            return PipelineResult(
                faces=[
                    ProcessedFace(
                        bbox=face["bbox"],
                        track_id=int(face["track_id"]),
                        name=None,
                        similarity=0.0,
                        recognized=False,
                        label="服务连接中",
                    )
                    for face in faces
                ],
                face_count=len(faces),
            )
        self.checkin_store.update_from_frame(data)
        self._last_db_person_count = int(data.get("db_person_count") or 0)
        self.db_embeddings = [None] * self._last_db_person_count
        return PipelineResult(
            faces=[ProcessedFace(**item) for item in data.get("faces") or []],
            face_count=int(data.get("face_count") or len(faces)),
            checked_in_names=list(data.get("checked_in_names") or []),
        )

    @staticmethod
    def _face_payload(face: dict) -> dict:
        embedding = face.get("embedding")
        return {
            "track_id": int(face["track_id"]),
            "bbox": [int(v) for v in face["bbox"]],
            "embedding": np.asarray(embedding, dtype=np.float32).tolist()
            if embedding is not None
            else None,
            "det_score": float(face.get("det_score") or 0.0),
            "kps": face.get("kps"),
            "gender": face.get("gender"),
            "fresh_detection": bool(face.get("fresh_detection", True)),
        }

    def checkout(self, name: str) -> int | None:
        try:
            data = self.client.post(
                "/api/v1/recognition/check-out",
                {"name": name},
                timeout=8,
            )
        except ApiClientError as exc:
            logger.warning("远程签退失败: %s", exc)
            return None
        payload = data.get("data") or {}
        if payload.get("checkedOut"):
            self.checkin_store.mark_checked_out(name)
        return payload.get("durationMinutes")

    def update_embeddings(self, db_embeddings: list) -> None:
        self.db_embeddings = [None] * self._last_db_person_count

    def shutdown(self) -> None:
        return


def _quote_path(value: str) -> str:
    from urllib.parse import quote

    return quote(value, safe="")

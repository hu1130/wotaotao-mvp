"""Shared face recognition -> attendance -> event pipeline."""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Protocol

from config import (
    ALLOW_REPEAT_CHECKIN,
    CHECKED_IN_REENTRY_MIN_ABSENT_SECONDS,
    CHECKED_IN_REPEAT_REENTRY_MIN_ABSENT_SECONDS,
    CHECKED_IN_STARE_COOLDOWN_SECONDS,
    CHECKED_IN_STARE_TRIGGER_SECONDS,
    CROWD_THRESHOLD,
    IDLE_LONG_THRESHOLD,
    MAX_PROCESS_FACES,
    REPEAT_FEEDBACK_COOLDOWN_SECONDS,
    STRANGER_GREET_COOLDOWN_SECONDS,
    STRANGER_POST_GREETING_SUPPRESS_SECONDS,
    STRANGER_REENTRY_MIN_ABSENT_SECONDS,
    STRANGER_STARE_COOLDOWN_SECONDS,
    STRANGER_STARE_TRIGGER_SECONDS,
    TENANT_ID,
    UNKNOWN_ENROLL_MAX_EMPLOYEE_SIMILARITY,
    UNKNOWN_ENROLL_MIN_HITS,
    STRANGER_MIN_UNKNOWN_HITS,
)
from core.attendance_policy import should_checkout_checked_in_presence
from core.attendance_db import AttendanceDB
from core.embedding_matcher import EmbeddingMatcher
from core.events import EventBus
from core.face_utils import (
    can_enroll_unknown_visitor,
    check_face_quality,
    is_complete_face_for_stranger,
)
from core.gender import gender_display_name, gender_salutation
from core.recognition_cache import RecognitionCache
from core.recognizer import FaceRecognizer
from core.tracker import FaceTrackerABC
from core.unknown_visitors import UnknownVisitorStore
from core.vote import VoteBuffer

logger = logging.getLogger(__name__)


class CheckInStateStore(Protocol):
    def is_checked_in_today(self, name: str, tenant_id: str | None = None) -> bool: ...

    def is_checked_out_today(self, name: str, tenant_id: str | None = None) -> bool: ...

    def mark_checked_in(self, name: str, tenant_id: str | None = None) -> None: ...

    def reset_checkin(self, name: str, tenant_id: str | None = None) -> None: ...


@dataclass
class ProcessedFace:
    bbox: list[int]
    track_id: int
    name: str | None
    similarity: float
    recognized: bool
    label: str
    checked_in_now: bool = False
    unknown_visitor_id: str | None = None
    returning_unknown: bool = False
    gender: str | None = None
    stranger_presence_key: str | None = None
    person_id: str | None = None


@dataclass
class PipelineResult:
    faces: list[ProcessedFace]
    face_count: int
    checked_in_names: list[str] = field(default_factory=list)


@dataclass
class CheckedInPresence:
    present: bool = False
    entered_at: float = 0.0
    last_seen_at: float = 0.0
    absent_since: float = 0.0
    last_stare_at: float = 0.0
    stare_triggered: bool = False


@dataclass
class StrangerPresence:
    present: bool = False
    entered_at: float = 0.0
    last_seen_at: float = 0.0
    absent_since: float = 0.0
    greeted: bool = False
    last_stare_at: float = 0.0
    stare_triggered: bool = False
    last_greeted_at: float = 0.0


class RecognitionPipeline:
    """Owns shared recognition, voting, attendance, and behavior event logic."""

    def __init__(
        self,
        recognizer: FaceRecognizer,
        tracker: FaceTrackerABC,
        db_embeddings: list,
        attendance_db: AttendanceDB,
        checkin_tracker: CheckInStateStore,
        vote_buffer: VoteBuffer,
        rec_cache: RecognitionCache,
        event_bus: EventBus,
        unknown_visitors: UnknownVisitorStore,
    ):
        self.recognizer = recognizer
        self.tracker = tracker
        self.db_embeddings = db_embeddings
        self.matcher = EmbeddingMatcher(db_embeddings)
        self.attendance_db = attendance_db
        self.checkin_tracker = checkin_tracker
        self.vote_buffer = vote_buffer
        self.rec_cache = rec_cache
        self.event_bus = event_bus
        self.unknown_visitors = unknown_visitors
        self.tenant_id = TENANT_ID

        self.last_face_time = 0.0
        self.idle_long_sent = False
        self.crowd_sent = False
        self.repeat_feedback_times: dict[str, float] = {}
        self.checked_in_presence: dict[str, CheckedInPresence] = {}
        self.stranger_presence: dict[str, StrangerPresence] = {}
        self.unknown_hits: dict[int, int] = {}
        self.last_stranger_greeted_at = 0.0
        self.stranger_followup_suppressed_until = 0.0
        self.pending_checkins: set[str] = set()
        self.pending_lock = threading.Lock()
        self.attendance_lock = threading.Lock()
        self.attendance_executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="AttendanceWorker",
        )

    def update_embeddings(self, db_embeddings: list) -> None:
        self.db_embeddings = db_embeddings
        self.matcher.update(db_embeddings)

    def shutdown(self) -> None:
        self.attendance_executor.shutdown(wait=False, cancel_futures=True)

    def process_frame(self, frame) -> PipelineResult:
        now = time.time()
        faces = self.tracker.update(frame, self.recognizer)
        active_ids = {face["track_id"] for face in faces}
        self.vote_buffer.cleanup_inactive(active_ids)
        self.rec_cache.cleanup(active_ids)
        self._cleanup_unknown_hits(active_ids)
        self._handle_scene_events(len(faces), now)

        processed: list[ProcessedFace] = []
        checked_in_names: list[str] = []
        active_checked_in_names: set[str] = set()
        active_stranger_keys: set[str] = set()
        needs_fresh_detection = False

        for face in self._select_business_faces(faces, frame.shape):
            item = self._process_face(face, frame.shape, now)
            processed.append(item)
            if item.checked_in_now and item.name:
                checked_in_names.append(item.name)
            if (
                item.recognized
                and item.name
                and self.checkin_tracker.is_checked_in_today(item.name, self.tenant_id)
            ):
                active_checked_in_names.add(item.name)
            if not item.recognized and item.stranger_presence_key:
                active_stranger_keys.add(item.stranger_presence_key)
            if self._needs_more_detection(item):
                needs_fresh_detection = True

        self._handle_crowd_events(self._unique_presence_count(processed), now)
        self._mark_absent_checked_in_names(active_checked_in_names, now)
        self._mark_absent_strangers(active_stranger_keys, now)

        if needs_fresh_detection:
            self.tracker.request_detection()

        return PipelineResult(
            faces=processed,
            face_count=len(faces),
            checked_in_names=checked_in_names,
        )

    @staticmethod
    def _select_business_faces(faces: list[dict], frame_shape) -> list[dict]:
        if MAX_PROCESS_FACES <= 0 or len(faces) <= MAX_PROCESS_FACES:
            return faces

        frame_h, frame_w = frame_shape[:2]
        frame_cx = frame_w / 2.0
        frame_cy = frame_h / 2.0

        def priority(face: dict) -> tuple[int, float]:
            x1, y1, x2, y2 = face["bbox"]
            width = max(0, x2 - x1)
            height = max(0, y2 - y1)
            area = width * height
            cx = (x1 + x2) / 2.0
            cy = (y1 + y2) / 2.0
            center_distance = ((cx - frame_cx) ** 2 + (cy - frame_cy) ** 2) ** 0.5
            return (-area, center_distance)

        return sorted(faces, key=priority)[:MAX_PROCESS_FACES]

    def checkout(self, name: str) -> int | None:
        with self.attendance_lock:
            duration = self.attendance_db.check_out(name, self.tenant_id)
        if duration is None:
            logger.warning("签退失败: %s 今日没有未签退签到记录", name)
            return None
        self.checkin_tracker.reset_checkin(name, self.tenant_id)
        self.event_bus.checkout(name, 0, duration, self.tenant_id)
        return duration

    def _cleanup_unknown_hits(self, active_ids: set[int]) -> None:
        for track_id in list(self.unknown_hits.keys()):
            if track_id not in active_ids:
                self.unknown_hits.pop(track_id, None)

    def _handle_scene_events(self, face_count: int, now: float) -> None:
        if face_count > 0:
            if self.last_face_time == 0.0 or self.idle_long_sent:
                self.event_bus.attention()
                self.last_face_time = 0.0
            self.idle_long_sent = False
            self.last_face_time = now
            return

        if (
            self.last_face_time > 0
            and now - self.last_face_time > IDLE_LONG_THRESHOLD
            and not self.idle_long_sent
        ):
            self.event_bus.idle_long()
            self.idle_long_sent = True

    def _handle_crowd_events(self, unique_face_count: int, now: float) -> None:
        if unique_face_count < CROWD_THRESHOLD:
            self.crowd_sent = False
            return
        if now < self.stranger_followup_suppressed_until:
            logger.info(
                "crowd 触发被陌生人招呼静默窗口抑制: unique=%d until=%.1f",
                unique_face_count,
                self.stranger_followup_suppressed_until,
            )
            return
        if self.crowd_sent:
            return
        self.event_bus.crowd(unique_face_count)
        self.crowd_sent = True

    @staticmethod
    def _unique_presence_count(faces: list[ProcessedFace]) -> int:
        keys: set[str] = set()
        for face in faces:
            if face.recognized and face.name:
                keys.add(f"known:{face.name}")
            elif face.stranger_presence_key:
                keys.add(face.stranger_presence_key)
            else:
                keys.add(f"track:{face.track_id}")
        return len(keys)

    def _process_face(self, face: dict, frame_shape, now: float) -> ProcessedFace:
        bbox = face["bbox"]
        track_id = face["track_id"]
        quality = check_face_quality(face, frame_shape)
        if not quality.passed:
            cached_name, cached_sim = self.rec_cache.get_known(track_id)
            if cached_name is not None:
                return self._handle_recognized_face(
                    cached_name,
                    float(cached_sim or 0.0),
                    bbox,
                    track_id,
                    now,
                    decision="cached",
                )
            cached_visitor = self.rec_cache.get_cached_unknown(track_id)
            if cached_visitor is not None:
                presence_key = f"visitor:{cached_visitor.visitor_id}"
                return ProcessedFace(
                    bbox=bbox,
                    track_id=track_id,
                    name=None,
                    similarity=0.0,
                    recognized=False,
                    label=f"{cached_visitor.label} · 追踪中",
                    unknown_visitor_id=cached_visitor.visitor_id,
                    returning_unknown=cached_visitor.is_returning,
                    gender=cached_visitor.gender,
                    stranger_presence_key=presence_key,
                )
            return ProcessedFace(
                bbox=bbox,
                track_id=track_id,
                name=None,
                similarity=0.0,
                recognized=False,
                label=quality.label,
            )

        fresh_detection = face.get("fresh_detection", True)
        name, similarity, decision = self._recognize(
            track_id,
            face["embedding"],
            fresh_detection=fresh_detection,
        )
        similarity = float(similarity or 0.0)

        if name is None:
            return self._handle_unknown_face(
                face,
                bbox,
                track_id,
                similarity,
                frame_shape,
                now,
            )

        return self._handle_recognized_face(
            name,
            similarity,
            bbox,
            track_id,
            now,
            decision,
            fresh_detection,
            face["embedding"],
        )

    def _recognize(
        self,
        track_id: int,
        embedding,
        fresh_detection: bool,
    ) -> tuple[str | None, float, str]:
        name, similarity = self.rec_cache.get_known(track_id)
        if name is not None:
            return name, float(similarity or 0.0), "cached"

        known_miss_similarity = self.rec_cache.get_known_miss(track_id, embedding)
        if known_miss_similarity is not None:
            return None, known_miss_similarity, "reject"

        candidate = self.matcher.match_candidate(embedding)
        if candidate.decision == "reject" and fresh_detection:
            self.rec_cache.set_known_miss(track_id, candidate.similarity, embedding)
        elif candidate.decision == "review":
            logger.debug(
                "识别进入复核区: %s sim=%.3f",
                candidate.name,
                candidate.similarity,
            )
        return candidate.name, float(candidate.similarity or 0.0), candidate.decision

    def _handle_unknown_face(
        self,
        face: dict,
        bbox: list[int],
        track_id: int,
        similarity: float,
        frame_shape,
        now: float,
    ) -> ProcessedFace:
        complete_face = is_complete_face_for_stranger(bbox, frame_shape)
        fresh_detection = face.get("fresh_detection", True)
        if complete_face and fresh_detection:
            self.unknown_hits[track_id] = self.unknown_hits.get(track_id, 0) + 1

        visitor = self.rec_cache.get_cached_unknown(track_id)
        if visitor is not None:
            logger.debug(
                "未知访客沿用当前 track 绑定: track=%s visitor=%s",
                track_id,
                visitor.label,
            )
        if visitor is None and complete_face and fresh_detection:
            early_match = self.unknown_visitors.match_only(face["embedding"])
            if early_match is not None:
                visitor = early_match
                self.rec_cache.set_unknown(
                    track_id,
                    visitor.visitor_id,
                    visitor.label,
                    visitor.similarity,
                    visitor.is_returning,
                    visitor.gender,
                    face["embedding"],
                )

        can_enroll = self._can_enroll_unknown_visitor(
            face,
            frame_shape,
            similarity,
            track_id,
        )
        track_presence_key = f"track:{track_id}" if complete_face else ""
        presence_key = (
            f"visitor:{visitor.visitor_id}" if visitor else track_presence_key
        )

        if visitor is not None:
            self._link_stranger_presence(track_presence_key, presence_key)

        if can_enroll and fresh_detection:
            if visitor is None:
                visitor = self.unknown_visitors.match_or_create(
                    face["embedding"],
                    gender=face.get("gender"),
                )
                self.rec_cache.set_unknown(
                    track_id,
                    visitor.visitor_id,
                    visitor.label,
                    visitor.similarity,
                    visitor.is_returning,
                    visitor.gender,
                    face["embedding"],
                )
                presence_key = f"visitor:{visitor.visitor_id}"
                self._link_stranger_presence(track_presence_key, presence_key)

            if (
                self._can_greet_stranger(
                    presence_key,
                    is_returning=visitor.is_returning,
                    now=now,
                )
                and self.recognizer.should_log_stranger()
            ):
                effective_gender = visitor.gender or face.get("gender")
                salutation = gender_salutation(effective_gender)
                self.event_bus.stranger(
                    visitor_label=visitor.label,
                    is_returning=visitor.is_returning,
                    gender=effective_gender,
                    salutation=salutation,
                )
                logger.info(
                    "检测到%s: %s, %s (sim=%.3f)",
                    "回访未知访客" if visitor.is_returning else "新未知访客",
                    visitor.label,
                    gender_display_name(effective_gender),
                    visitor.similarity,
                )
                self._mark_stranger_greeted(presence_key)
        elif (
            complete_face
            and fresh_detection
            and self.unknown_hits.get(track_id, 0) >= STRANGER_MIN_UNKNOWN_HITS
            and self._can_greet_stranger(
                presence_key,
                is_returning=visitor.is_returning if visitor else False,
                now=now,
            )
            and self.recognizer.should_log_stranger()
        ):
            effective_gender = visitor.gender if visitor else face.get("gender")
            self.event_bus.stranger(
                visitor_label=visitor.label if visitor else None,
                is_returning=visitor.is_returning if visitor else False,
                gender=effective_gender,
                salutation=gender_salutation(effective_gender),
            )
            logger.info(
                "检测到未知访客但未入库: sim=%.3f, hits=%d, gender=%s, returning=%s",
                similarity,
                self.unknown_hits.get(track_id, 0),
                gender_display_name(effective_gender),
                visitor.is_returning if visitor else False,
            )
            self._mark_stranger_greeted(presence_key)

        if presence_key:
            self._handle_stranger_presence(
                presence_key,
                now,
                visitor.gender or face.get("gender") if visitor else face.get("gender"),
            )

        if complete_face and not fresh_detection:
            label = "识别中"
        else:
            label = self._unknown_label(visitor, complete_face)
        result_gender = (
            visitor.gender or face.get("gender") if visitor else face.get("gender")
        )

        return ProcessedFace(
            bbox=bbox,
            track_id=track_id,
            name=None,
            similarity=similarity,
            recognized=False,
            label=label,
            unknown_visitor_id=visitor.visitor_id if visitor else None,
            returning_unknown=visitor.is_returning if visitor else False,
            gender=result_gender,
            stranger_presence_key=presence_key or None,
        )

    @staticmethod
    def _unknown_label(visitor, complete_face: bool) -> str:
        if visitor is None:
            return "未知访客" if complete_face else "请正对摄像头"
        if visitor.is_returning:
            return f"{visitor.label} · 又见面"
        return f"{visitor.label} · 初次记录"

    def _can_enroll_unknown_visitor(
        self,
        face: dict,
        frame_shape,
        employee_similarity: float,
        track_id: int,
    ) -> bool:
        if self.unknown_hits.get(track_id, 0) < UNKNOWN_ENROLL_MIN_HITS:
            return False
        if employee_similarity >= UNKNOWN_ENROLL_MAX_EMPLOYEE_SIMILARITY:
            return False
        return can_enroll_unknown_visitor(face, frame_shape)

    def _handle_recognized_face(
        self,
        name: str,
        similarity: float,
        bbox: list[int],
        track_id: int,
        now: float,
        decision: str = "accept",
        fresh_detection: bool = True,
        embedding=None,
    ) -> ProcessedFace:
        try:
            vote_confirmed = False
            if decision in {"accept", "review"}:
                if not fresh_detection:
                    return self._face(
                        bbox,
                        track_id,
                        name,
                        similarity,
                        f"确认中 · {name}",
                    )
                voted_name = self.vote_buffer.vote(track_id, name, similarity, now)
                if voted_name is None:
                    return self._face(
                        bbox,
                        track_id,
                        name,
                        similarity,
                        f"确认中 · {name}",
                    )
                name = voted_name
                vote_confirmed = True
                if embedding is not None:
                    self.rec_cache.set_known(
                        track_id,
                        name,
                        similarity,
                        embedding,
                    )

            if not ALLOW_REPEAT_CHECKIN and self.checkin_tracker.is_checked_out_today(
                name, self.tenant_id
            ):
                return self._face(bbox, track_id, name, similarity, f"已签退 · {name}")

            if not ALLOW_REPEAT_CHECKIN and self.checkin_tracker.is_checked_in_today(
                name, self.tenant_id
            ):
                if self._should_checkout_on_presence(name, now):
                    duration = self.checkout(name)
                    if duration is not None:
                        self.checked_in_presence.pop(name, None)
                        logger.info(
                            "18点后识别触发签退: name=%s duration=%s",
                            name,
                            duration,
                        )
                        return self._face(
                            bbox,
                            track_id,
                            name,
                            similarity,
                            f"已签退 · {name}",
                        )
                self._handle_checked_in_presence(name, now)
                return self._face(bbox, track_id, name, similarity, f"已签到 · {name}")

            if self._is_pending_checkin(name):
                return self._face(bbox, track_id, name, similarity, f"签到中 · {name}")

            voted_name = name if vote_confirmed or decision == "cached" else None
            if voted_name is None:
                return self._face(bbox, track_id, name, similarity, name)

            self._add_pending_checkin(voted_name)
            self.attendance_executor.submit(
                self._complete_checkin,
                voted_name,
                similarity,
            )
            return self._face(
                bbox,
                track_id,
                voted_name,
                similarity,
                f"已签到 · {voted_name}",
                checked_in_now=True,
            )
        except Exception as exc:
            logger.warning("人脸业务处理失败 (%s): %s", name, exc)
            return self._face(bbox, track_id, name, similarity, f"处理中 · {name}")

    def _complete_checkin(self, name: str, similarity: float) -> None:
        try:
            with self.attendance_lock:
                is_first = not self.attendance_db.has_any_record(name, self.tenant_id)
                is_returning = not is_first and not self.attendance_db.has_record_today(
                    name, self.tenant_id
                )
                row_id = self.attendance_db.check_in(name, self.tenant_id)
            self.checkin_tracker.mark_checked_in(name, self.tenant_id)
            self._mark_checked_in_present(name, time.time())
            self.repeat_feedback_times[name] = time.time()
            self.event_bus.checkin(
                name,
                row_id,
                similarity,
                is_first=is_first,
                is_returning=is_returning,
                tenant_id=self.tenant_id,
            )
            logger.info(
                "签到成功: %s (sim=%.3f, row=%s, first=%s, returning=%s)",
                name,
                similarity,
                row_id,
                is_first,
                is_returning,
            )
        except Exception as exc:
            logger.warning("签到落库失败 (%s): %s", name, exc)
        finally:
            self._discard_pending_checkin(name)

    def _is_pending_checkin(self, name: str) -> bool:
        with self.pending_lock:
            return name in self.pending_checkins

    def _add_pending_checkin(self, name: str) -> None:
        with self.pending_lock:
            self.pending_checkins.add(name)

    def _discard_pending_checkin(self, name: str) -> None:
        with self.pending_lock:
            self.pending_checkins.discard(name)

    def _maybe_repeat_feedback(self, name: str, now: float) -> None:
        last_repeat = self.repeat_feedback_times.get(name, 0.0)
        if now - last_repeat >= REPEAT_FEEDBACK_COOLDOWN_SECONDS:
            self.event_bus.repeat_checkin(name)
            self.repeat_feedback_times[name] = now

    def _handle_checked_in_presence(self, name: str, now: float) -> None:
        state = self.checked_in_presence.get(name)
        if state is None:
            self.checked_in_presence[name] = CheckedInPresence(
                present=True,
                entered_at=now,
                last_seen_at=now,
            )
            return

        was_absent = not state.present and state.absent_since > 0
        absent_seconds = now - state.absent_since if was_absent else 0.0
        if was_absent:
            state.entered_at = now
            state.last_stare_at = 0.0
            state.stare_triggered = False
        if was_absent and absent_seconds >= CHECKED_IN_REPEAT_REENTRY_MIN_ABSENT_SECONDS:
            self._maybe_repeat_feedback(name, now)
        elif not state.present:
            logger.debug(
                "checked_in_stare 重新入场仅重置注视计时: name=%s absent=%.1fs",
                name,
                absent_seconds,
            )

        state.present = True
        state.last_seen_at = now
        state.absent_since = 0.0

        dwell_seconds = now - state.entered_at
        if dwell_seconds < CHECKED_IN_STARE_TRIGGER_SECONDS:
            return
        if state.stare_triggered:
            return
        if (
            state.last_stare_at > 0
            and now - state.last_stare_at < CHECKED_IN_STARE_COOLDOWN_SECONDS
        ):
            return
        self.event_bus.checked_in_stare(name)
        state.last_stare_at = now
        state.stare_triggered = True

    def _mark_checked_in_present(self, name: str, now: float) -> None:
        state = self.checked_in_presence.setdefault(name, CheckedInPresence())
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

    def _should_checkout_on_presence(self, name: str, now: float) -> bool:
        return should_checkout_checked_in_presence(
            self.checked_in_presence.get(name),
            now_seconds=now,
            min_absent_seconds=CHECKED_IN_REENTRY_MIN_ABSENT_SECONDS,
        )

    def _mark_absent_checked_in_names(
        self, active_checked_in_names: set[str], now: float
    ) -> None:
        for name, state in list(self.checked_in_presence.items()):
            if name in active_checked_in_names:
                continue
            if state.present:
                state.present = False
                state.absent_since = now
                state.entered_at = 0.0
                state.last_stare_at = 0.0
                state.stare_triggered = False

    def _handle_stranger_presence(
        self, presence_key: str, now: float, gender: str | None
    ) -> None:
        state = self.stranger_presence.get(presence_key)
        if state is None:
            self.stranger_presence[presence_key] = StrangerPresence(
                present=True,
                entered_at=now,
                last_seen_at=now,
            )
            logger.info(
                "stranger_presence 新建: key=%s, entered_at=%.1f",
                presence_key,
                now,
            )
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
            if not brief_absent:
                state.greeted = False
            state.last_seen_at = now
            state.absent_since = 0.0
            logger.info(
                "stranger_presence 重新入场: key=%s, entered_at=%.1f, brief=%s",
                presence_key,
                state.entered_at,
                brief_absent,
            )
            return

        state.last_seen_at = now
        if not self._is_recorded_stranger_presence_key(presence_key):
            return
        dwell_seconds = now - state.entered_at
        if now < self.stranger_followup_suppressed_until:
            logger.debug(
                "stranger_stare 等待陌生人招呼静默窗口: key=%s remaining=%.1fs",
                presence_key,
                self.stranger_followup_suppressed_until - now,
            )
            return
        if dwell_seconds < STRANGER_STARE_TRIGGER_SECONDS:
            logger.debug(
                "stranger_presence 等待: key=%s, dwell=%.1fs/%.1fs",
                presence_key,
                dwell_seconds,
                STRANGER_STARE_TRIGGER_SECONDS,
            )
            return
        if state.stare_triggered:
            return
        if (
            state.last_stare_at > 0
            and now - state.last_stare_at < STRANGER_STARE_COOLDOWN_SECONDS
        ):
            return
        logger.info(
            "stranger_stare 触发: key=%s, dwell=%.1fs, last_stare=%.1f",
            presence_key,
            dwell_seconds,
            state.last_stare_at,
        )
        self.event_bus.stranger_stare(salutation=gender_salutation(gender))
        state.last_stare_at = now
        state.stare_triggered = True

    @staticmethod
    def _is_recorded_stranger_presence_key(presence_key: str) -> bool:
        return presence_key.startswith("visitor:")

    def _can_greet_stranger(
        self, presence_key: str, is_returning: bool, now: float
    ) -> bool:
        if not presence_key:
            return True
        if (
            self.last_stranger_greeted_at > 0
            and now - self.last_stranger_greeted_at < STRANGER_GREET_COOLDOWN_SECONDS
        ):
            return False
        state = self.stranger_presence.setdefault(presence_key, StrangerPresence())
        if (
            state.last_greeted_at > 0
            and now - state.last_greeted_at < STRANGER_GREET_COOLDOWN_SECONDS
        ):
            return False
        if is_returning and state.absent_since > 0:
            absent_seconds = now - state.absent_since
            if absent_seconds < STRANGER_REENTRY_MIN_ABSENT_SECONDS:
                return False
        if state.present and state.greeted:
            return False
        return True

    def _mark_stranger_greeted(self, presence_key: str) -> None:
        if not presence_key:
            return
        state = self.stranger_presence.setdefault(presence_key, StrangerPresence())
        now = time.time()
        state.greeted = True
        state.last_greeted_at = now
        state.last_stare_at = now
        state.entered_at = now
        self.last_stranger_greeted_at = now
        self.stranger_followup_suppressed_until = now + max(
            0.0,
            STRANGER_POST_GREETING_SUPPRESS_SECONDS,
        )
        logger.info(
            "陌生人招呼后静默窗口开启: key=%s suppress_until=%.1f",
            presence_key,
            self.stranger_followup_suppressed_until,
        )

    def _link_stranger_presence(self, track_key: str, visitor_key: str) -> None:
        if not track_key or not visitor_key or track_key == visitor_key:
            return
        track_state = self.stranger_presence.get(track_key)
        visitor_state = self.stranger_presence.get(visitor_key)
        if track_state is None:
            logger.debug(
                "link_stranger 跳过: track_key=%s 无state, visitor_key=%s",
                track_key,
                visitor_key,
            )
            return
        if visitor_state is None:
            self.stranger_presence[visitor_key] = StrangerPresence(
                present=track_state.present,
                entered_at=track_state.entered_at,
                last_seen_at=track_state.last_seen_at,
                absent_since=0.0,
                greeted=track_state.greeted,
                last_stare_at=track_state.last_stare_at,
                stare_triggered=track_state.stare_triggered,
                last_greeted_at=track_state.last_greeted_at,
            )
            return
        if not visitor_state.present and track_state.present:
            visitor_state.present = True
            visitor_state.entered_at = track_state.entered_at
            visitor_state.last_seen_at = track_state.last_seen_at
            visitor_state.last_stare_at = track_state.last_stare_at
            visitor_state.stare_triggered = track_state.stare_triggered
        visitor_state.greeted = visitor_state.greeted or track_state.greeted
        visitor_state.last_greeted_at = max(
            visitor_state.last_greeted_at, track_state.last_greeted_at
        )

    def _mark_absent_strangers(
        self, active_stranger_keys: set[str], now: float
    ) -> None:
        for key, state in list(self.stranger_presence.items()):
            if key in active_stranger_keys:
                continue
            if state.present:
                state.present = False
                state.absent_since = now
                state.entered_at = 0.0
                state.last_stare_at = 0.0
                state.stare_triggered = False

    @staticmethod
    def _face(
        bbox: list[int],
        track_id: int,
        name: str,
        similarity: float,
        label: str,
        checked_in_now: bool = False,
    ) -> ProcessedFace:
        return ProcessedFace(
            bbox=bbox,
            track_id=track_id,
            name=name,
            similarity=similarity,
            recognized=True,
            label=label,
            checked_in_now=checked_in_now,
        )

    @staticmethod
    def _needs_more_detection(face: ProcessedFace) -> bool:
        return face.label.startswith("确认中") or face.label == "识别中"

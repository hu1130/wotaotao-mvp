"""Thread-safe camera-driven person conversation state machine."""

from __future__ import annotations

import hashlib
import logging
import threading
import time
import uuid
from collections import Counter
from collections.abc import Iterable
from typing import Protocol

from config import (
    PERSON_SESSION_ACQUIRE_SECONDS,
    PERSON_SESSION_ABSENT_SECONDS,
    PERSON_SESSION_SILENT_RELEASE_SECONDS,
    RUNTIME_SCOPE_LOCK_SHARDS,
    RUNTIME_SCOPE_IDLE_TTL_SECONDS,
)
from core.concurrency import StripedLock
from core.person_sessions.models import (
    DevicePersonSession,
    ObservedPerson,
    PersonSessionSnapshot,
    PersonSessionState,
)
from core.runtime_scope import RuntimeScope

logger = logging.getLogger("uvicorn.error")


class PersonMemoryRepository(Protocol):
    def start_conversation(self, **kwargs) -> None: ...

    def append_turn(self, **kwargs) -> None: ...

    def recent_context(self, person_id: str, *, limit: int = 6) -> list[dict]: ...

    def end_conversation(self, conversation_id: str, *, reason: str) -> None: ...

    def close(self) -> None: ...


class PersonConversationManager:
    def __init__(
        self,
        memory: PersonMemoryRepository,
        *,
        acquire_seconds: float = PERSON_SESSION_ACQUIRE_SECONDS,
        absent_seconds: float = PERSON_SESSION_ABSENT_SECONDS,
        silent_release_seconds: float = PERSON_SESSION_SILENT_RELEASE_SECONDS,
    ) -> None:
        self.memory = memory
        self.acquire_seconds = max(0.0, acquire_seconds)
        self.absent_seconds = max(1.0, absent_seconds)
        self.silent_release_seconds = max(30.0, silent_release_seconds)
        self._sessions: dict[str, DevicePersonSession] = {}
        self._registry_lock = threading.RLock()
        self._scope_locks = StripedLock(RUNTIME_SCOPE_LOCK_SHARDS)

    def observe(
        self,
        device_id: str,
        faces: Iterable[dict],
        *,
        frame_width: int,
        frame_height: int,
        tenant_id: str = "",
        now: float | None = None,
    ) -> PersonSessionSnapshot:
        now = time.time() if now is None else now
        scope = RuntimeScope.build(tenant_id, device_id)
        device_id = scope.device_id
        face_list = list(faces)
        observed = self._normalize_faces(face_list, frame_width, frame_height)
        unknown_count = sum(
            1
            for face in face_list
            if not face.get("recognized") or not str(face.get("name") or "").strip()
        )
        persistence: list[tuple[str, tuple]] = []
        with self._scope_locks.for_key(scope.key):
            session = self._session_for(scope)
            previous_state = session.state
            previous_participants = session.participants
            session.last_observed_at = now
            session.participants = self._participant_names(
                session,
                observed,
                unknown_count=unknown_count,
            )
            owner = next((item for item in observed if item.person_id == session.owner_id), None)
            if session.owner_id:
                if owner is not None:
                    session.owner_last_seen_at = now
                    session.owner_absent_since = 0.0
                    session.state = self._present_state(session, now)
                else:
                    if session.owner_absent_since <= 0:
                        session.owner_absent_since = now
                    self._track_candidate(session, observed, now)
                    if session.candidate_id and now - session.candidate_since >= self.acquire_seconds:
                        logger.info(
                            "人物会话主人缺席且新候选人稳定，切换主人: device=%s old=%s new=%s absent_seconds=%.3f acquire_seconds=%.3f",
                            session.device_id,
                            session.owner_name,
                            session.candidate_name,
                            max(0.0, now - session.owner_absent_since),
                            max(0.0, now - session.candidate_since),
                        )
                        persistence.append(
                            ("end", (session.conversation_id, "owner_replaced"))
                        )
                        self._activate_candidate_if_ready(session, now, persistence)
                    elif now - session.owner_absent_since >= self.absent_seconds:
                        persistence.append(
                            ("end", (session.conversation_id, "owner_absent"))
                        )
                        self._clear_owner(session)
                        self._track_candidate(session, observed, now)
                        self._activate_candidate_if_ready(session, now, persistence)
                    else:
                        session.state = PersonSessionState.OWNER_GRACE
            else:
                self._track_candidate(session, observed, now)
                self._activate_candidate_if_ready(session, now, persistence)
            session.participants = self._participant_names(
                session,
                observed,
                unknown_count=unknown_count,
            )
            if Counter(session.participants) != Counter(previous_participants):
                logger.debug(
                    "人物会话参与者变化: device=%s conversation=%s owner=%s participants=%s",
                    device_id,
                    session.conversation_id or "(none)",
                    session.owner_name or "(none)",
                    list(session.participants),
                )
            snapshot = self._snapshot(session, now)
            if previous_state != session.state:
                logger.info(
                    "人物会话状态变更: device=%s %s->%s conversation=%s owner=%s participants=%s",
                    device_id,
                    previous_state.value,
                    session.state.value,
                    session.conversation_id or "(none)",
                    session.owner_name or "(none)",
                    list(session.participants),
                )
        self._persist(persistence)
        return snapshot

    def tick(self, *, now: float | None = None) -> list[PersonSessionSnapshot]:
        now = time.time() if now is None else now
        persistence: list[tuple[str, tuple]] = []
        snapshots: list[PersonSessionSnapshot] = []
        stale_scope_keys: list[str] = []
        with self._registry_lock:
            sessions = list(self._sessions.items())
        for scope_key, session in sessions:
            with self._scope_locks.for_key(scope_key):
                previous_state = session.state
                if session.owner_id and now - session.owner_last_seen_at >= self.absent_seconds:
                    persistence.append(("end", (session.conversation_id, "recognition_stale")))
                    self._clear_owner(session)
                elif session.owner_id and not session.owner_absent_since:
                    session.state = self._present_state(session, now)
                if previous_state != session.state:
                    logger.info(
                        "人物会话定时状态变更: device=%s %s->%s conversation=%s",
                        session.device_id,
                        previous_state.value,
                        session.state.value,
                        session.conversation_id or "(none)",
                    )
                snapshots.append(self._snapshot(session, now))
                if (
                    not session.owner_id
                    and session.last_observed_at > 0
                    and now - session.last_observed_at > RUNTIME_SCOPE_IDLE_TTL_SECONDS
                ):
                    stale_scope_keys.append(scope_key)
        if stale_scope_keys:
            with self._registry_lock:
                for scope_key in stale_scope_keys:
                    self._sessions.pop(scope_key, None)
            logger.info(
                "人物会话空闲运行域已清理: count=%d",
                len(stale_scope_keys),
            )
        self._persist(persistence)
        return snapshots

    def get(
        self,
        device_id: str,
        *,
        tenant_id: str = "",
        now: float | None = None,
    ) -> PersonSessionSnapshot:
        now = time.time() if now is None else now
        scope = RuntimeScope.build(tenant_id, device_id)
        with self._scope_locks.for_key(scope.key):
            session = self._session_for(scope)
            if session.owner_id and not session.owner_absent_since:
                session.state = self._present_state(session, now)
            return self._snapshot(session, now)

    def note_speech(
        self,
        device_id: str,
        *,
        tenant_id: str = "",
        now: float | None = None,
    ) -> PersonSessionSnapshot:
        now = time.time() if now is None else now
        scope = RuntimeScope.build(tenant_id, device_id)
        device_id = scope.device_id
        with self._scope_locks.for_key(scope.key):
            session = self._session_for(scope)
            if session.owner_id:
                previous_state = session.state
                session.last_activity_at = now
                if not session.owner_absent_since:
                    session.state = PersonSessionState.ACTIVE
                if previous_state == PersonSessionState.SUSPENDED_IDLE:
                    logger.info(
                        "人物静默会话因再次说话恢复: device=%s conversation=%s owner=%s",
                        device_id,
                        session.conversation_id,
                        session.owner_name,
                    )
            return self._snapshot(session, now)

    def append_turn(
        self,
        snapshot: PersonSessionSnapshot,
        *,
        user_text: str,
        assistant_text: str,
    ) -> None:
        if not snapshot.has_owner or not snapshot.conversation_id:
            logger.info("匿名或无归属语音轮次不写个人记忆: device=%s", snapshot.device_id)
            return
        attributed = snapshot.memory_write_allowed
        privacy_reason = ""
        self.memory.append_turn(
            conversation_id=snapshot.conversation_id,
            person_id=snapshot.owner_id,
            user_text=user_text,
            assistant_text=assistant_text,
            attributed=attributed,
            privacy_epoch=snapshot.privacy_epoch,
            privacy_reason=privacy_reason,
            tenant_id=snapshot.tenant_id,
        )
        logger.info(
            "人物会话轮次已持久化: conversation=%s owner=%s participants=%s attributed=%s privacy_epoch=%d privacy_reason=%s user_chars=%d answer_chars=%d",
            snapshot.conversation_id,
            snapshot.owner_name,
            list(snapshot.participants),
            attributed,
            snapshot.privacy_epoch,
            privacy_reason or "none",
            len(user_text),
            len(assistant_text),
        )

    def recent_context(self, snapshot: PersonSessionSnapshot, *, limit: int = 6) -> list[dict]:
        if not snapshot.memory_read_allowed:
            logger.info(
                "人物会话无可信主人，不读取个人记忆: device=%s conversation=%s",
                snapshot.device_id,
                snapshot.conversation_id or "(none)",
            )
            return []
        return self.memory.recent_context(snapshot.owner_id, limit=limit)

    def close(self) -> None:
        self.memory.close()

    def _activate_candidate_if_ready(
        self,
        session: DevicePersonSession,
        now: float,
        persistence: list[tuple[str, tuple]],
    ) -> None:
        if not session.candidate_id:
            session.state = PersonSessionState.IDLE
            return
        if now - session.candidate_since < self.acquire_seconds:
            session.state = PersonSessionState.CANDIDATE
            return
        session.owner_id = session.candidate_id
        session.owner_name = session.candidate_name
        session.owner_last_seen_at = now
        session.owner_absent_since = 0.0
        session.started_at = now
        session.last_activity_at = now
        session.conversation_id = f"{session.tenant_id}-{uuid.uuid4().hex}"
        session.privacy_epoch = 0
        session.state = PersonSessionState.ACTIVE
        session.candidate_id = ""
        session.candidate_name = ""
        session.candidate_since = 0.0
        persistence.append(
            (
                "start",
                (
                    session.conversation_id,
                    session.device_id,
                    session.tenant_id,
                    session.owner_id,
                    session.owner_name,
                    session.privacy_epoch,
                ),
            )
        )

    def _track_candidate(
        self,
        session: DevicePersonSession,
        observed: list[ObservedPerson],
        now: float,
    ) -> None:
        candidates = [item for item in observed if item.person_id != session.owner_id]
        candidate = candidates[0] if candidates else None
        if candidate is None:
            session.candidate_id = ""
            session.candidate_name = ""
            session.candidate_since = 0.0
            if not session.owner_id:
                session.state = PersonSessionState.IDLE
            return
        if candidate.person_id != session.candidate_id:
            session.candidate_id = candidate.person_id
            session.candidate_name = candidate.person_name
            session.candidate_since = now
        if not session.owner_id:
            session.state = PersonSessionState.CANDIDATE

    def _present_state(self, session: DevicePersonSession, now: float) -> PersonSessionState:
        if now - session.last_activity_at >= self.silent_release_seconds:
            return PersonSessionState.SUSPENDED_IDLE
        return PersonSessionState.ACTIVE

    @staticmethod
    def _clear_owner(session: DevicePersonSession) -> None:
        session.state = PersonSessionState.IDLE
        session.conversation_id = ""
        session.owner_id = ""
        session.owner_name = ""
        session.owner_last_seen_at = 0.0
        session.owner_absent_since = 0.0
        session.started_at = 0.0
        session.last_activity_at = 0.0
        session.participants = ()
        session.privacy_epoch += 1

    def _persist(self, actions: list[tuple[str, tuple]]) -> None:
        for action, args in actions:
            try:
                if action == "start":
                    (
                        conversation_id,
                        device_id,
                        tenant_id,
                        person_id,
                        person_name,
                        privacy_epoch,
                    ) = args
                    self.memory.start_conversation(
                        conversation_id=conversation_id,
                        device_id=device_id,
                        person_id=person_id,
                        person_name=person_name,
                        privacy_epoch=privacy_epoch,
                        tenant_id=tenant_id,
                    )
                elif action == "end":
                    conversation_id, reason = args
                    if conversation_id:
                        self.memory.end_conversation(conversation_id, reason=reason)
            except Exception:
                logger.exception("人物会话持久化失败: action=%s args=%s", action, args)

    @staticmethod
    def _normalize_faces(
        faces: Iterable[dict],
        frame_width: int,
        frame_height: int,
    ) -> list[ObservedPerson]:
        center_x = max(1, frame_width) / 2.0
        center_y = max(1, frame_height) / 2.0
        by_person: dict[str, ObservedPerson] = {}
        for face in faces:
            name = str(face.get("name") or "").strip()
            if not face.get("recognized") or not name:
                continue
            bbox = [int(value) for value in (face.get("bbox") or [0, 0, 0, 0])[:4]]
            if len(bbox) != 4:
                continue
            x1, y1, x2, y2 = bbox
            area = max(0, x2 - x1) * max(0, y2 - y1)
            face_x = (x1 + x2) / 2.0
            face_y = (y1 + y2) / 2.0
            person_id = str(face.get("person_id") or "").strip()[:120]
            if not person_id:
                person_id = PersonConversationManager.person_id_for_name(name)
            item = ObservedPerson(
                person_id=person_id,
                person_name=name[:80],
                track_id=int(face.get("track_id") or 0),
                similarity=float(face.get("similarity") or 0.0),
                area=area,
                center_distance=((face_x - center_x) ** 2 + (face_y - center_y) ** 2) ** 0.5,
            )
            previous = by_person.get(person_id)
            if previous is None or (-item.area, item.center_distance) < (
                -previous.area,
                previous.center_distance,
            ):
                by_person[person_id] = item
        return sorted(by_person.values(), key=lambda item: (-item.area, item.center_distance))

    @staticmethod
    def _participant_names(
        session: DevicePersonSession,
        observed: list[ObservedPerson],
        *,
        unknown_count: int = 0,
    ) -> tuple[str, ...]:
        names = [
            item.person_name for item in observed if item.person_id != session.owner_id
        ]
        names.extend("未知访客" for _ in range(max(0, unknown_count)))
        return tuple(names)

    @staticmethod
    def _snapshot(session: DevicePersonSession, now: float) -> PersonSessionSnapshot:
        absent_seconds = (
            max(0.0, now - session.owner_absent_since)
            if session.owner_absent_since
            else 0.0
        )
        replacement_pending = bool(session.owner_absent_since and session.candidate_id)
        state = (
            PersonSessionState.CANDIDATE
            if replacement_pending
            else session.state
        )
        return PersonSessionSnapshot(
            device_id=session.device_id,
            state=state,
            tenant_id=session.tenant_id,
            conversation_id="" if replacement_pending else session.conversation_id,
            owner_id="" if replacement_pending else session.owner_id,
            owner_name="" if replacement_pending else session.owner_name,
            participants=session.participants,
            started_at=session.started_at,
            last_activity_at=session.last_activity_at,
            owner_absent_seconds=absent_seconds,
            privacy_epoch=session.privacy_epoch,
        )

    @staticmethod
    def person_id_for_name(name: str) -> str:
        digest = hashlib.sha256(name.strip().encode("utf-8")).hexdigest()[:24]
        return f"employee:{digest}"

    def _session_for(self, scope: RuntimeScope) -> DevicePersonSession:
        with self._registry_lock:
            return self._sessions.setdefault(
                scope.key,
                DevicePersonSession(
                    device_id=scope.device_id,
                    tenant_id=scope.tenant_id,
                ),
            )


_manager: PersonConversationManager | None = None
_manager_lock = threading.Lock()


def get_person_conversation_manager() -> PersonConversationManager:
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                from core.person_sessions.memory import get_person_memory_repository

                _manager = PersonConversationManager(get_person_memory_repository())
    return _manager

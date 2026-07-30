"""API-only recognition path for split client/server deployment."""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.request
from dataclasses import asdict, dataclass
from datetime import date
from typing import Callable

import numpy as np

from config import (
    ALLOW_REPEAT_CHECKIN,
    AVATAR_SERVER_URL,
    CHECKED_IN_REENTRY_MIN_ABSENT_SECONDS,
    DEVICE_ID,
    TENANT_ID,
    MAX_PROCESS_FACES,
    REPEAT_FEEDBACK_COOLDOWN_SECONDS,
)
from core.api_client import ApiClientError, SignedApiClient
from core.attendance_policy import should_checkout_checked_in_presence
from core.attendance_db import AttendanceDB
from core.embedding_matcher import EmbeddingMatcher
from core.events import EventBus
from core.face_utils import check_face_quality
from core.recognition_cache import RecognitionCache
from core.recognition_pipeline import PipelineResult, ProcessedFace
from core.recognizer import FaceRecognizer
from core.redis_checkin import RedisCheckIn
from core.tracker import FaceTrackerABC
from core.vector_db import VectorDB
from core.vote import VoteBuffer
from core.daily_tts_texts import choose_text
from core.tts_texts import TTS_TEXTS

logger = logging.getLogger(__name__)


@dataclass
class RemoteCheckedInPresence:
    present: bool = False
    entered_at: float = 0.0
    last_seen_at: float = 0.0
    absent_since: float = 0.0


class RemoteRecognitionService:
    """Server-side matcher/check-in service used by device API-only clients."""

    def __init__(self, avatar_url: str = AVATAR_SERVER_URL):
        self.attendance_db = AttendanceDB()
        self.checkin_store = RedisCheckIn()
        self.event_bus = EventBus()
        self.vote_buffer = VoteBuffer()
        self.rec_cache = RecognitionCache()
        self.avatar_url = avatar_url.rstrip("/")
        self.matcher = EmbeddingMatcher([])
        self.db_embeddings: list[tuple[str, np.ndarray]] = []
        self._lock = threading.RLock()
        self._last_embeddings_load = 0.0
        self._last_stranger_event_at = 0.0
        self._last_repeat_feedback: dict[str, float] = {}
        self._checked_in_presence: dict[str, RemoteCheckedInPresence] = {}
        self.reload_embeddings(force=True)

    def reload_embeddings(self, force: bool = False) -> None:
        now = time.time()
        if not force and now - self._last_embeddings_load < 10.0:
            return
        embeddings = VectorDB().get_all_embeddings()
        with self._lock:
            self.db_embeddings = embeddings
            self.matcher.update(embeddings)
            self._last_embeddings_load = now
        logger.info("远程识别底库已加载: %d 条向量", len(embeddings))

    def process_frame(self, payload: dict) -> dict:
        self.reload_embeddings(force=False)
        frame_shape = (int(payload["frame_height"]), int(payload["frame_width"]), 3)
        active_ids = {int(face["track_id"]) for face in payload.get("faces") or []}
        self.vote_buffer.cleanup_inactive(active_ids)
        self.rec_cache.cleanup(active_ids)

        processed = []
        checked_in_names = []
        active_checked_in_names: set[str] = set()
        for face in self._select_faces(payload.get("faces") or [], frame_shape):
            item = self._process_face(face, frame_shape)
            processed.append(asdict(item))
            if item.checked_in_now and item.name:
                checked_in_names.append(item.name)
            if (
                item.recognized
                and item.name
                and self.checkin_store.is_checked_in_today(item.name, TENANT_ID)
            ):
                active_checked_in_names.add(item.name)
                self._mark_checked_in_present(item.name, time.time())
        self._mark_absent_checked_in_names(active_checked_in_names, time.time())
        return {
            "faces": processed,
            "face_count": len(payload.get("faces") or []),
            "checked_in_names": checked_in_names,
            "db_person_count": len({name for name, _ in self.db_embeddings}),
            "today_count": self.checkin_store.get_today_count(TENANT_ID),
        }

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

    def _process_face(self, face: dict, frame_shape) -> ProcessedFace:
        track_id = int(face["track_id"])
        bbox = [int(v) for v in face["bbox"]]
        quality = check_face_quality(face, frame_shape)
        if not quality.passed:
            cached_name, cached_sim = self.rec_cache.get_known(track_id)
            if cached_name:
                return self._complete_known_face(
                    bbox,
                    track_id,
                    cached_name,
                    cached_sim or 0.0,
                )
            return ProcessedFace(
                bbox=bbox,
                track_id=track_id,
                name=None,
                similarity=0.0,
                recognized=False,
                label=quality.label,
                gender=face.get("gender"),
            )

        embedding = face.get("embedding")
        if not embedding:
            return ProcessedFace(
                bbox=bbox,
                track_id=track_id,
                name=None,
                similarity=0.0,
                recognized=False,
                label="识别中",
                gender=face.get("gender"),
            )

        vector = np.asarray(embedding, dtype=np.float32)
        cached_name, cached_sim = self.rec_cache.get_known(track_id)
        if cached_name is not None:
            return self._complete_known_face(
                bbox,
                track_id,
                cached_name,
                float(cached_sim or 0.0),
            )

        known_miss = self.rec_cache.get_known_miss(track_id, vector)
        if known_miss is not None:
            self._maybe_stranger_event(face)
            return self._unknown_face(bbox, track_id, known_miss, face.get("gender"))

        candidate = self.matcher.match_candidate(vector)
        similarity = float(candidate.similarity or 0.0)
        if candidate.decision == "reject":
            self.rec_cache.set_known_miss(track_id, similarity, vector)
            self._maybe_stranger_event(face)
            return self._unknown_face(bbox, track_id, similarity, face.get("gender"))

        if not face.get("fresh_detection", True):
            return ProcessedFace(
                bbox=bbox,
                track_id=track_id,
                name=candidate.name,
                similarity=similarity,
                recognized=True,
                label=f"确认中 · {candidate.name}",
                gender=face.get("gender"),
            )

        voted_name = self.vote_buffer.vote(track_id, candidate.name, similarity, time.time())
        if voted_name is None:
            return ProcessedFace(
                bbox=bbox,
                track_id=track_id,
                name=candidate.name,
                similarity=similarity,
                recognized=True,
                label=f"确认中 · {candidate.name}",
                gender=face.get("gender"),
            )

        self.rec_cache.set_known(track_id, voted_name, similarity, vector)
        return self._complete_known_face(bbox, track_id, voted_name, similarity)

    def _complete_known_face(
        self,
        bbox: list[int],
        track_id: int,
        name: str,
        similarity: float,
    ) -> ProcessedFace:
        if not ALLOW_REPEAT_CHECKIN and self.checkin_store.is_checked_out_today(
            name, TENANT_ID
        ):
            return self._known_face(bbox, track_id, name, similarity)
        if not ALLOW_REPEAT_CHECKIN and self.checkin_store.is_checked_in_today(
            name, TENANT_ID
        ):
            now = time.time()
            if self._should_checkout_on_presence(name, now):
                checkout_result = self.checkout(name)
                if checkout_result.get("checkedOut"):
                    self._checked_in_presence.pop(name, None)
                    logger.info(
                        "远程18点后识别触发签退: name=%s duration=%s",
                        name,
                        checkout_result.get("durationMinutes"),
                    )
                    return self._known_face(bbox, track_id, name, similarity)
            self._maybe_repeat_event(name)
            return self._known_face(bbox, track_id, name, similarity)
        try:
            is_first = not self.attendance_db.has_any_record(name, TENANT_ID)
            is_returning = not is_first and not self.attendance_db.has_record_today(
                name, TENANT_ID
            )
            row_id = self.attendance_db.check_in(name, TENANT_ID)
            self.checkin_store.mark_checked_in(name, TENANT_ID)
            self.event_bus.publish(
                "checkin",
                {
                    "name": name,
                    "row_id": row_id,
                    "similarity": round(similarity, 4),
                    "time": time.time(),
                },
            )
            self._post_avatar_event(
                {
                    "type": "check_in",
                    "name": name,
                    "is_first": is_first,
                    "is_returning": is_returning,
                }
            )
            speech_type = "first_time" if is_first else "returning" if is_returning else "check_in"
            self._post_speech_event(speech_type, name)
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
    ) -> ProcessedFace:
        if self.checkin_store.is_checked_out_today(name, TENANT_ID):
            label = f"已签退 · {name}"
        elif self.checkin_store.is_checked_in_today(name, TENANT_ID):
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

    def _maybe_stranger_event(self, face: dict) -> None:
        now = time.time()
        if now - self._last_stranger_event_at < 30.0:
            return
        self._last_stranger_event_at = now
        payload = {
            "type": "stranger",
            "visitor_label": "未知访客",
            "is_returning": False,
            "gender": face.get("gender"),
            "time": now,
        }
        self.event_bus.publish("stranger_detected", payload)
        self._post_avatar_event(payload)
        self._post_speech_event("stranger", "访客")

    def _maybe_repeat_event(self, name: str) -> None:
        now = time.time()
        last = self._last_repeat_feedback.get(name, 0.0)
        if now - last < REPEAT_FEEDBACK_COOLDOWN_SECONDS:
            return
        self._last_repeat_feedback[name] = now
        self.event_bus.publish("repeat_checkin", {"name": name, "time": now})
        self._post_avatar_event({"type": "repeat", "name": name})
        self._post_speech_event("repeat", name)

    def _mark_checked_in_present(self, name: str, now: float) -> None:
        state = self._checked_in_presence.setdefault(name, RemoteCheckedInPresence())
        state.present = True
        state.entered_at = state.entered_at or now
        state.last_seen_at = now
        state.absent_since = 0.0

    def _mark_absent_checked_in_names(
        self,
        active_checked_in_names: set[str],
        now: float,
    ) -> None:
        for name, state in list(self._checked_in_presence.items()):
            if name in active_checked_in_names:
                continue
            if state.present:
                state.present = False
                state.absent_since = now

    def _should_checkout_on_presence(self, name: str, now: float) -> bool:
        return should_checkout_checked_in_presence(
            self._checked_in_presence.get(name),
            now_seconds=now,
            min_absent_seconds=CHECKED_IN_REENTRY_MIN_ABSENT_SECONDS,
        )

    def checkout(self, name: str) -> dict:
        duration = self.attendance_db.check_out(name, TENANT_ID)
        if duration is None:
            return {"checkedOut": False, "reason": "no open check-in record"}
        self.checkin_store.reset_checkin(name, TENANT_ID)
        self.event_bus.publish(
            "checkout",
            {"name": name, "duration_minutes": duration, "time": time.time()},
        )
        self._post_avatar_event({"type": "check_out", "name": name})
        self._post_speech_event("check_out", name)
        return {"checkedOut": True, "durationMinutes": duration}

    def _post_avatar_event(self, payload: dict) -> None:
        try:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(
                f"{self.avatar_url}/event",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=0.5).close()
        except Exception as exc:
            logger.debug("远程 avatar 事件发送失败: %s", exc)

    def _post_speech_event(self, event_type: str, name: str) -> None:
        text = self._speech_text(event_type, name)
        if not text:
            return
        self._post_avatar_event(
            {
                "type": "speech",
                "event_type": event_type,
                "name": name,
                "text": text,
            }
        )

    @staticmethod
    def _speech_text(event_type: str, name: str) -> str:
        require_name = event_type in {"check_in", "check_out", "first_time", "returning", "repeat"}
        text = choose_text(TTS_TEXTS, event_type, require_placeholder=require_name)
        if not text:
            text = choose_text(TTS_TEXTS, event_type)
        if not text:
            return ""
        if "{}" in text:
            return text.format(name or "访客")
        return text


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
        self._processed_frames = 0
        self._last_frame_log_at = 0.0
        logger.info(
            "远程识别客户端已初始化: base_url=%s device_id=%s",
            self.client.base_url,
            DEVICE_ID,
        )

    def process_frame(self, frame) -> PipelineResult:
        faces = self.tracker.update(frame, self.recognizer)
        h, w = frame.shape[:2]
        self._processed_frames += 1
        payload = {
            "tenant_id": TENANT_ID,
            "device_id": DEVICE_ID,
            "frame_width": int(w),
            "frame_height": int(h),
            "faces": [self._face_payload(face) for face in faces],
        }
        now = time.time()
        should_log_frame = now - self._last_frame_log_at >= 5.0
        if should_log_frame:
            logger.info(
                "远程识别发帧: seq=%d size=%dx%d faces=%d url=%s",
                self._processed_frames,
                int(w),
                int(h),
                len(faces),
                self.client.base_url,
            )
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
        if should_log_frame:
            self._last_frame_log_at = now
            logger.info(
                "远程识别响应: seq=%d server_face_count=%d checked_in=%d db_person_count=%d today=%d",
                self._processed_frames,
                int(data.get("face_count") or 0),
                len(data.get("checked_in_names") or []),
                int(data.get("db_person_count") or 0),
                int(data.get("today_count") or 0),
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

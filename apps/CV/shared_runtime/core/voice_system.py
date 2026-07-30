"""Queue based TTS, audio playback, and Live2D event pipeline."""

from __future__ import annotations

import hashlib
import heapq
import itertools
import json
import logging
import os
import queue
import random
import threading
import time
import urllib.request
from collections import OrderedDict
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Optional

from config import (
    AUDIO_QUEUE_MAXSIZE,
    AVATAR_SERVER_URL,
    FIXED_TTS_TENANT_ID,
    TTS_CACHE_DIR,
    TTS_QUEUE_MAXSIZE,
    TTS_VOICE,
    TTS_VOICE_BY_MODEL,
)
from core.avatar_state import AvatarStateCache, get_avatar_state_cache
from core.daily_tts_texts import choose_text
from core.fixed_tts import FixedTtsClient
from core.tts_texts import TTS_TEXTS

logger = logging.getLogger(__name__)

AVATAR_AUDIO_LOCK_MAX_MS = 120000
AVATAR_AUDIO_RELEASE_GRACE_MS = 1800
TTS_PRIORITY_ATTENDANCE = 5
TTS_PRIORITY_GESTURE = 10
TTS_PRIORITY_DEFAULT = 30
TTS_PRIORITY_SENTINEL = -100
ATTENDANCE_SPEECH_EVENTS = {"check_in", "check_out", "first_time", "returning"}


def tts_priority_for_event(event_type: str) -> int:
    if event_type in ATTENDANCE_SPEECH_EVENTS:
        return TTS_PRIORITY_ATTENDANCE
    if event_type.startswith("gesture_"):
        return TTS_PRIORITY_GESTURE
    return TTS_PRIORITY_DEFAULT


def tts_priority_for_item(item) -> int:
    if item is None:
        return TTS_PRIORITY_SENTINEL
    explicit_priority = getattr(item, "priority", None)
    if explicit_priority is not None:
        return int(explicit_priority)
    return tts_priority_for_event(getattr(item, "event_type", ""))


@dataclass(frozen=True)
class TTSRequest:
    event_type: str
    text: str
    name: str = ""
    voice: str = TTS_VOICE
    tenant_id: str = ""
    priority: int | None = None


@dataclass(frozen=True)
class AudioJob:
    path: str
    event_type: str
    name: str = ""
    text: str = ""
    priority: int | None = None


@dataclass(frozen=True)
class Live2DAction:
    event_type: str
    payload: dict


class PrioritizedWorkQueue:
    """Priority queue wrapper with the small Queue API used by worker threads."""

    def __init__(self, maxsize: int = 0):
        self._queue: queue.PriorityQueue = queue.PriorityQueue(maxsize=maxsize)
        self._sequence = itertools.count()

    def put_nowait(self, item) -> None:
        self._queue.put_nowait(self._entry_for(item))

    def put(self, item, block: bool = True, timeout: float | None = None) -> None:
        self._queue.put(self._entry_for(item), block=block, timeout=timeout)

    def get(self, block: bool = True, timeout: float | None = None):
        return self._queue.get(block=block, timeout=timeout)[2]

    def get_nowait(self):
        return self._queue.get_nowait()[2]

    def task_done(self) -> None:
        self._queue.task_done()

    def empty(self) -> bool:
        return self._queue.empty()

    def qsize(self) -> int:
        return self._queue.qsize()

    def discard_lower_priority_than(self, priority: int) -> int:
        removed = 0
        with self._queue.mutex:
            kept = []
            for entry in self._queue.queue:
                item = entry[2]
                if item is not None and entry[0] > priority:
                    removed += 1
                else:
                    kept.append(entry)
            if removed == 0:
                return 0
            heapq.heapify(kept)
            self._queue.queue[:] = kept
            self._queue.unfinished_tasks = max(
                0,
                self._queue.unfinished_tasks - removed,
            )
            self._queue.not_full.notify_all()
        return removed

    def has_priority_at_most(self, priority: int) -> bool:
        with self._queue.mutex:
            return any(entry[0] <= priority for entry in self._queue.queue)

    def _entry_for(self, item) -> tuple[int, int, object]:
        return (tts_priority_for_item(item), next(self._sequence), item)


class SpeechSuppressionGate:
    """Combines local realtime-dialog suppression with browser voice-chat locks."""

    def __init__(self, avatar_state: AvatarStateCache | None = None):
        self._local = threading.Event()
        self._avatar_state = avatar_state or get_avatar_state_cache()

    def set(self) -> None:
        self._local.set()

    def clear(self) -> None:
        self._local.clear()

    def is_set(self) -> bool:
        if self._local.is_set():
            return True
        return self._avatar_state.is_external_audio_locked()

    def is_local_set(self) -> bool:
        return self._local.is_set()


class TTSAudioCache:
    """Disk backed hash cache with a small in-memory LRU index."""

    def __init__(self, cache_dir: str = TTS_CACHE_DIR, max_items: int = 256):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_items = max_items
        self._lock = threading.Lock()
        self._lru: OrderedDict[str, str] = OrderedDict()

    def key_for(self, request: TTSRequest, cache_material: str) -> str:
        raw = "|".join(
            [
                "fixed-tts",
                request.event_type,
                request.text,
                cache_material,
            ]
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def path_for_key(self, key: str, extension: str = ".mp3") -> str:
        return str(self.cache_dir / f"{key}{extension}")

    def get(self, key: str, extension: str = ".mp3") -> Optional[str]:
        with self._lock:
            path = self._lru.get(key)
            if not path:
                path = self.path_for_key(key, extension)
            if not path:
                return None
            if os.path.exists(path) and os.path.getsize(path) > 0:
                self._lru[key] = path
                self._lru.move_to_end(key)
                return path
            self._lru.pop(key, None)
            return None

    def put(self, key: str, path: str) -> None:
        with self._lock:
            self._lru[key] = path
            self._lru.move_to_end(key)
            while len(self._lru) > self.max_items:
                self._lru.popitem(last=False)

class TTSWorkerThread(threading.Thread):
    """Consumes TTS requests, uses cache, and emits playable audio jobs."""

    def __init__(
        self,
        tts_queue: queue.Queue,
        audio_queue: queue.Queue,
        cache: TTSAudioCache,
        client,
        speech_suppressed: threading.Event | None = None,
    ):
        super().__init__(name="TTSWorkerThread", daemon=True)
        self.tts_queue = tts_queue
        self.audio_queue = audio_queue
        self.cache = cache
        self.client = client
        self.speech_suppressed = speech_suppressed
        self._stop_event = threading.Event()
        self._loop = None

    def stop(self) -> None:
        self._stop_event.set()
        self.tts_queue.put(None)

    def run(self) -> None:
        import asyncio

        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            while not self._stop_event.is_set():
                request = self.tts_queue.get()
                if request is None:
                    self.tts_queue.task_done()
                    break
                try:
                    if self._is_suppressed():
                        logger.debug(
                            "TTS request suppressed by realtime dialog: %s",
                            request.event_type,
                        )
                        continue
                    cache_material = self.client.build_cache_material(request)
                    key = self.cache.key_for(request, cache_material)
                    extension = self.client.cache_extension(request)
                    path = self.cache.get(key, extension)
                    if not path:
                        path = self.cache.path_for_key(key, extension)
                        tmp_path = f"{path}.tmp{extension}"
                        self._run_tts_coroutine(
                            self.client.synthesize_to_file_async(request, tmp_path)
                        )
                        os.replace(tmp_path, path)
                        self.cache.put(key, path)
                        logger.info("Fixed TTS generated: event=%s path=%s", request.event_type, path)
                    else:
                        logger.debug("TTS cache hit: event=%s text=%s", request.event_type, request.text)
                    if self._is_suppressed():
                        logger.debug(
                            "TTS audio job suppressed by realtime dialog: %s",
                            request.event_type,
                        )
                        continue
                    self.audio_queue.put(
                        AudioJob(
                            path=path,
                            event_type=request.event_type,
                            name=request.name,
                            text=request.text,
                            priority=tts_priority_for_item(request),
                        )
                    )
                except Exception as exc:
                    logger.warning(
                        "TTS request skipped (%s): %s", request.event_type, exc
                    )
                finally:
                    self.tts_queue.task_done()
        finally:
            try:
                self._loop.run_until_complete(self._loop.shutdown_asyncgens())
            finally:
                asyncio.set_event_loop(None)
                self._loop.close()
                self._loop = None

    def _run_tts_coroutine(self, coroutine) -> None:
        import asyncio

        try:
            self._loop.run_until_complete(coroutine)
        finally:
            pending = [
                task for task in asyncio.all_tasks(self._loop) if not task.done()
            ]
            if pending:
                for task in pending:
                    task.cancel()
                self._loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )

    def _is_suppressed(self) -> bool:
        return bool(self.speech_suppressed and self.speech_suppressed.is_set())


class AudioPlayerThread(threading.Thread):
    """Serial audio playback worker. Face recognition never waits on it."""

    def __init__(
        self,
        audio_queue: queue.Queue,
        live2d: Live2DController | None = None,
        speech_suppressed: threading.Event | None = None,
        avatar_state: AvatarStateCache | None = None,
    ):
        super().__init__(name="AudioPlayerThread", daemon=True)
        self.audio_queue = audio_queue
        self.live2d = live2d
        self.speech_suppressed = speech_suppressed
        self.avatar_state = avatar_state or get_avatar_state_cache()
        self._stop_event = threading.Event()
        self._busy_lock = threading.Lock()
        self._active_job = False
        self._active_priority: int | None = None

    def stop(self) -> None:
        self._stop_event.set()
        self.audio_queue.put(None)

    def stop_current_playback(self) -> None:
        try:
            import pygame.mixer

            if pygame.mixer.get_init() and pygame.mixer.music.get_busy():
                pygame.mixer.music.stop()
        except Exception:
            pass

    def run(self) -> None:
        import pygame.mixer

        pygame.mixer.init()
        while not self._stop_event.is_set():
            job = self.audio_queue.get()
            if job is None:
                break
            speech_end_sent = False
            try:
                self._set_active_job(True, tts_priority_for_item(job))
                if self._is_suppressed():
                    logger.debug(
                        "Audio job suppressed by realtime dialog: %s", job.event_type
                    )
                    continue
                self._set_avatar_audio_lock(True, owner="legacy_tts")
                pygame.mixer.music.load(job.path)
                if self.live2d is not None and job.text:
                    self.live2d.enqueue(
                        "speech",
                        {
                            "event_type": job.event_type,
                            "name": job.name,
                            "text": job.text,
                        },
                    )
                pygame.mixer.music.play()
                interrupted = False
                while pygame.mixer.music.get_busy() and not self._stop_event.is_set():
                    if self._is_realtime_priority_active():
                        pygame.mixer.music.stop()
                        interrupted = True
                        break
                    time.sleep(0.02)
                if interrupted:
                    logger.info(
                        "Legacy TTS interrupted; forcing speech_end: event=%s priority=%s",
                        job.event_type,
                        tts_priority_for_item(job),
                    )
                if self.live2d is not None and job.text:
                    self.live2d.enqueue("speech_end", {"event_type": job.event_type})
                    speech_end_sent = True
            except Exception as exc:
                logger.warning("Audio playback failed (%s): %s", job.path, exc)
            finally:
                if self.live2d is not None and job.text and not speech_end_sent:
                    self.live2d.enqueue("speech_end", {"event_type": job.event_type})
                self._set_active_job(False)
                self._set_avatar_audio_lock(False, owner="legacy_tts")
                self.audio_queue.task_done()

    def is_busy(self) -> bool:
        with self._busy_lock:
            return self._active_job

    def active_priority(self) -> int | None:
        with self._busy_lock:
            return self._active_priority if self._active_job else None

    def _set_active_job(self, active: bool, priority: int | None = None) -> None:
        with self._busy_lock:
            self._active_job = active
            self._active_priority = priority if active else None

    def _is_suppressed(self) -> bool:
        return bool(self.speech_suppressed and self.speech_suppressed.is_set())

    def _is_realtime_priority_active(self) -> bool:
        if not self.speech_suppressed:
            return False
        local_check = getattr(self.speech_suppressed, "is_local_set", None)
        if callable(local_check):
            return bool(local_check())
        return bool(self.speech_suppressed.is_set())

    def _set_avatar_audio_lock(self, active: bool, owner: str) -> None:
        hold_ms = AVATAR_AUDIO_LOCK_MAX_MS if active else AVATAR_AUDIO_RELEASE_GRACE_MS
        try:
            self.avatar_state.set_audio_lock(
                active,
                hold_ms=hold_ms,
                owner=owner,
                timeout_seconds=0.2,
            )
        except Exception:
            logger.debug("Avatar audio lock update failed: owner=%s active=%s", owner, active)


class Live2DController(threading.Thread):
    """Asynchronous Live2D HTTP dispatcher."""

    def __init__(self, base_url: str = AVATAR_SERVER_URL):
        super().__init__(name="Live2DController", daemon=True)
        self.base_url = base_url.rstrip("/")
        self.action_queue: queue.Queue[Optional[Live2DAction]] = queue.Queue(maxsize=64)
        self._stop_event = threading.Event()

    def enqueue(self, event_type: str, payload: dict) -> None:
        try:
            self.action_queue.put_nowait(Live2DAction(event_type, payload))
        except queue.Full:
            logger.debug("Live2D action dropped because queue is full: %s", event_type)

    def clear_pending(self) -> None:
        _drain_queue(self.action_queue)

    def stop(self) -> None:
        self._stop_event.set()
        self.action_queue.put(None)

    def run(self) -> None:
        while not self._stop_event.is_set():
            action = self.action_queue.get()
            if action is None:
                break
            try:
                import json

                data = json.dumps(
                    {"type": action.event_type, **action.payload}, ensure_ascii=False
                ).encode("utf-8")
                req = urllib.request.Request(
                    f"{self.base_url}/event",
                    data=data,
                    headers={"Content-Type": "application/json"},
                )
                urllib.request.urlopen(req, timeout=0.5).close()
            except Exception:
                pass
            finally:
                self.action_queue.task_done()


class EmotionDecisionModule:
    """Converts face events into Live2D actions and key-event speech."""

    SPEECH_EVENTS = {
        "check_in",
        "check_out",
        "repeat",
        "checked_in_stare",
        "first_time",
        "returning",
        "stranger",
        "returning_stranger",
        "stranger_stare",
        "idle_long",
        "crowd",
    }
    SILENT_ACTIONS = {"attention"}
    NAME_POLICY = {
        "check_in": 1.0,
        "check_out": 1.0,
        "first_time": 1.0,
        "returning": 0.7,
        "returning_stranger": 0.6,
        "repeat": 0.35,
        "checked_in_stare": 0.0,
        "stranger": 1.0,
        "stranger_stare": 0.0,
        "idle_long": 0.0,
        "crowd": 0.0,
    }

    def __init__(
        self,
        tts_queue: queue.Queue,
        live2d: Live2DController,
        speech_suppressed: threading.Event | None = None,
        avatar_state: AvatarStateCache | None = None,
        enqueue_tts: Callable[[TTSRequest], bool] | None = None,
        tenant_id: str = "",
    ):
        self.tts_queue = tts_queue
        self.live2d = live2d
        self.speech_suppressed = speech_suppressed
        self.avatar_state = avatar_state or get_avatar_state_cache()
        self._enqueue_tts = enqueue_tts
        self._last_model_key = ""
        self._last_voice = TTS_VOICE
        self.tenant_id = tenant_id or FIXED_TTS_TENANT_ID

    def on_avatar_event(self, event_type: str, payload: dict) -> None:
        if self._is_suppressed():
            logger.debug("Avatar event suppressed by realtime dialog: %s", event_type)
            return

        self.live2d.enqueue(event_type, payload)

        if event_type in self.SILENT_ACTIONS:
            return

        speech_type = self._resolve_speech_type(event_type, payload)
        if speech_type not in self.SPEECH_EVENTS:
            return

        name = (
            payload.get("name")
            or payload.get("salutation")
            or payload.get("visitor_label")
            or "访客"
        )
        model_key = payload.get("model_key") or self._last_model_key
        text = self._pick_text(speech_type, name, model_key)
        if not text:
            return

        try:
            voice = payload.get("voice") or self._resolve_current_voice()
            request = TTSRequest(
                event_type=speech_type,
                text=text,
                name=name,
                voice=voice,
                tenant_id=self.tenant_id,
            )
            if self._enqueue_tts is not None:
                self._enqueue_tts(request)
            else:
                self.tts_queue.put_nowait(
                    replace(request, priority=tts_priority_for_item(request))
                )
        except queue.Full:
            logger.debug("TTS request dropped because queue is full: %s", speech_type)

    def _is_suppressed(self) -> bool:
        return bool(self.speech_suppressed and self.speech_suppressed.is_set())

    def _resolve_speech_type(self, event_type: str, payload: dict) -> str:
        if event_type == "stranger" and payload.get("is_returning"):
            return "returning_stranger"
        return event_type

    def _pick_text(self, event_type: str, name: str, model_key: str = "") -> str:
        include_name = self._should_include_name(event_type, name)
        text = choose_text(
            TTS_TEXTS,
            event_type,
            require_placeholder=include_name,
            model_key=model_key or self._last_model_key,
        )
        if not text and include_name:
            text = self._fallback_named_text(event_type)
        if not text:
            text = choose_text(
                TTS_TEXTS,
                event_type,
                model_key=model_key or self._last_model_key,
            )
        if not text:
            return ""
        if "{}" not in text:
            return text
        if include_name:
            return text.format(name)
        return ""

    @staticmethod
    def _fallback_named_text(event_type: str) -> str:
        if event_type == "stranger":
            return "{}，欢迎来到这里～"
        if event_type == "returning_stranger":
            return "{}，又见面啦，欢迎回来。"
        return ""

    def _should_include_name(self, event_type: str, name: str) -> bool:
        if not name or name == "访客":
            return False
        probability = self.NAME_POLICY.get(event_type, 0.5)
        return random.random() < probability

    def _resolve_current_voice(self) -> str:
        state = self.avatar_state.get_ready_state()
        if state.model:
            self._last_model_key = state.model
            self._last_voice = TTS_VOICE_BY_MODEL.get(state.model, TTS_VOICE)
        else:
            self._last_voice = TTS_VOICE_BY_MODEL.get(self._last_model_key, TTS_VOICE)
        return self._last_voice


class VoiceSystem:
    """Convenience wrapper that owns all speech related queues and workers."""

    def __init__(self, tenant_id: str | None = None):
        self.tenant_id = (tenant_id or FIXED_TTS_TENANT_ID or "default").strip()
        self.tts_queue = PrioritizedWorkQueue(
            maxsize=TTS_QUEUE_MAXSIZE
        )
        self.audio_queue = PrioritizedWorkQueue(
            maxsize=AUDIO_QUEUE_MAXSIZE
        )
        self.avatar_state = get_avatar_state_cache()
        self.speech_suppression = SpeechSuppressionGate(self.avatar_state)
        self.cache = TTSAudioCache()
        self.tts_client = FixedTtsClient(tenant_id=self.tenant_id)
        self.live2d = Live2DController()
        self._last_model_key = ""
        self._last_tts_voice = TTS_VOICE
        self.emotion = EmotionDecisionModule(
            self.tts_queue,
            self.live2d,
            speech_suppressed=self.speech_suppression,
            avatar_state=self.avatar_state,
            enqueue_tts=self.enqueue_tts,
            tenant_id=self.tenant_id,
        )
        self.tts_worker = TTSWorkerThread(
            self.tts_queue,
            self.audio_queue,
            self.cache,
            self.tts_client,
            speech_suppressed=self.speech_suppression,
        )
        self.audio_player = AudioPlayerThread(
            self.audio_queue,
            live2d=self.live2d,
            speech_suppressed=self.speech_suppression,
            avatar_state=self.avatar_state,
        )

    def start(self) -> None:
        self.live2d.start()
        self.tts_worker.start()
        self.audio_player.start()
        logger.info("Voice system started: Live2D + TTS worker + audio player")

    def stop(self) -> None:
        self.tts_worker.stop()
        self.audio_player.stop()
        self.live2d.stop()

    def is_legacy_audio_busy(self) -> bool:
        return (
            self.audio_player.is_busy()
            or not self.tts_queue.empty()
            or not self.audio_queue.empty()
        )

    def has_legacy_audio_at_or_above_priority(self, priority: int) -> bool:
        active_priority = self.audio_player.active_priority()
        return (
            (active_priority is not None and active_priority <= priority)
            or self.tts_queue.has_priority_at_most(priority)
            or self.audio_queue.has_priority_at_most(priority)
        )

    def resolve_current_tts_voice(self) -> tuple[str, str]:
        """Return the fixed-speech voice matching the active tenant policy."""
        state = self.avatar_state.get_ready_state()
        model_key = state.model or self._last_model_key
        requested_voice = TTS_VOICE_BY_MODEL.get(model_key, TTS_VOICE)
        request = TTSRequest(
            event_type="voice_probe",
            text="",
            voice=requested_voice,
            tenant_id=self.tenant_id,
        )
        resolved = self.tts_client.resolve_request(request)
        voice = resolved.speaker_id
        if model_key:
            self._last_model_key = model_key
        self._last_tts_voice = voice
        logger.debug(
            "Resolved current TTS voice: model=%s provider=%s voice=%s clone=%s version=%s",
            model_key or "default",
            resolved.provider,
            resolved.masked_speaker,
            resolved.clone_enabled,
            resolved.profile_version,
        )
        return voice, model_key

    def enqueue_tts(self, request: TTSRequest) -> bool:
        priority = tts_priority_for_item(request)
        request = replace(
            request,
            priority=priority,
            tenant_id=request.tenant_id or self.tenant_id,
        )
        self._preempt_lower_priority_legacy_audio(priority, request.event_type)
        try:
            self.tts_queue.put_nowait(request)
            return True
        except queue.Full:
            logger.debug("TTS request dropped because queue is full: %s", request.event_type)
            return False

    def _preempt_lower_priority_legacy_audio(
        self,
        priority: int,
        event_type: str,
    ) -> None:
        dropped_tts = self.tts_queue.discard_lower_priority_than(priority)
        dropped_audio = self.audio_queue.discard_lower_priority_than(priority)
        active_priority = self.audio_player.active_priority()
        if active_priority is not None and active_priority > priority:
            self.audio_player.stop_current_playback()
        if dropped_tts or dropped_audio or (
            active_priority is not None and active_priority > priority
        ):
            logger.info(
                "TTS priority preempt: event=%s priority=%d dropped_tts=%d dropped_audio=%d active_priority=%s",
                event_type,
                priority,
                dropped_tts,
                dropped_audio,
                active_priority,
            )

    def set_realtime_dialog_active(self, active: bool) -> None:
        if active:
            self.speech_suppression.set()
            self.audio_player.stop_current_playback()
            _drain_queue(self.tts_queue)
            _drain_queue(self.audio_queue)
            self.live2d.clear_pending()
            logger.debug(
                "Realtime dialog priority enabled; legacy speech queues cleared"
            )
        else:
            self.speech_suppression.clear()
            logger.debug("Realtime dialog priority released")


def _drain_queue(target: queue.Queue) -> None:
    while True:
        try:
            target.get_nowait()
            target.task_done()
        except queue.Empty:
            break

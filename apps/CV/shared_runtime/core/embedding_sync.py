"""Embedding sync service: monitors pgvector changes via LISTEN/NOTIFY and refreshes in-memory matcher."""

from __future__ import annotations

import logging
import select
import threading
import time

import psycopg2

from config import (
    PG_DATABASE,
    EMBEDDING_SYNC_POLL_INTERVAL,
    EMBEDDING_SYNC_DEBOUNCE,
)
from core.vector_db import VectorDB

logger = logging.getLogger(__name__)

NOTIFY_CHANNEL = "face_embeddings_changed"


class EmbeddingSyncService(threading.Thread):
    """Background daemon that keeps in-memory embeddings in sync with pgvector.

    Two-layer sync strategy:
      1. PostgreSQL LISTEN/NOTIFY (real-time, trigger-driven)
      2. Periodic polling fallback (catches missed notifications)

    The service holds a reference to the RecognitionPipeline and calls
    ``pipeline.update_embeddings()`` whenever a change is detected.
    """

    def __init__(self, pipeline, poll_interval: float | None = None):
        super().__init__(name="EmbeddingSyncService", daemon=True)
        self._pipeline = pipeline
        self._poll_interval = poll_interval or EMBEDDING_SYNC_POLL_INTERVAL
        self._debounce = EMBEDDING_SYNC_DEBOUNCE
        self._stop_event = threading.Event()
        self._vector_db: VectorDB | None = None
        self._last_person_count: int = -1
        self._last_vector_count: int = -1
        self._last_reload_at: float = 0.0
        self._refresh_requested = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()
        self._refresh_requested.set()

    def request_refresh(self) -> None:
        self._refresh_requested.set()

    def run(self) -> None:
        self._vector_db = VectorDB()
        self._initial_sync()

        listener = threading.Thread(
            target=self._listen_loop,
            name="PgNotifyListener",
            daemon=True,
        )
        listener.start()

        self._poll_loop()

    def _initial_sync(self) -> None:
        embeddings = self._vector_db.get_all_embeddings()
        self._pipeline.update_embeddings(embeddings)
        self._last_person_count = len({name for name, _ in embeddings})
        self._last_vector_count = len(embeddings)
        self._last_reload_at = time.time()
        logger.info(
            "底库初始同步完成: %d 人 / %d 条向量",
            self._last_person_count,
            self._last_vector_count,
        )

    def _listen_loop(self) -> None:
        while not self._stop_event.is_set():
            conn = None
            try:
                conn = psycopg2.connect(**VectorDB._connect_kwargs(PG_DATABASE))
                conn.autocommit = True
                cur = conn.cursor()
                cur.execute(f"LISTEN {NOTIFY_CHANNEL};")
                cur.close()
                logger.info("PostgreSQL LISTEN 已启动: channel=%s", NOTIFY_CHANNEL)

                while not self._stop_event.is_set():
                    try:
                        readable, _, _ = select.select([conn], [], [], 1.0)
                    except (OSError, ValueError):
                        break
                    if readable:
                        conn.poll()
                        while conn.notifies:
                            notify = conn.notifies.pop(0)
                            logger.info(
                                "收到数据库变更通知 (channel=%s, payload=%s)",
                                notify.channel,
                                notify.payload or "",
                            )
                            self._schedule_refresh()
            except Exception as exc:
                logger.warning("LISTEN 连接异常, 5 秒后重连: %s", exc)
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
            now = time.time()
            poll_due = (now - last_poll_at) >= self._poll_interval
            refresh_signaled = self._refresh_requested.wait(
                timeout=min(1.0, self._poll_interval)
            )
            if self._stop_event.is_set():
                break

            if refresh_signaled:
                self._refresh_requested.clear()
                self._do_refresh(source="notify")
                last_poll_at = time.time()
            elif poll_due:
                self._poll_check()
                last_poll_at = time.time()

    def _poll_check(self) -> None:
        try:
            person_count = len(self._vector_db)
            vector_count = self._vector_db.count_total_vectors()
        except Exception as exc:
            logger.warning("轮询检查失败: %s", exc)
            return

        if (
            person_count != self._last_person_count
            or vector_count != self._last_vector_count
        ):
            logger.info(
                "轮询检测到底库变更 (人: %d→%d, 向量: %d→%d)",
                self._last_person_count,
                person_count,
                self._last_vector_count,
                vector_count,
            )
            self._do_refresh(source="poll")

    def _schedule_refresh(self) -> None:
        self._refresh_requested.set()

    def _do_refresh(self, source: str = "unknown") -> None:
        now = time.time()
        if now - self._last_reload_at < self._debounce:
            return
        try:
            embeddings = self._vector_db.get_all_embeddings()
            self._pipeline.update_embeddings(embeddings)
            person_count = len({name for name, _ in embeddings})
            vector_count = len(embeddings)
            self._last_person_count = person_count
            self._last_vector_count = vector_count
            self._last_reload_at = time.time()
            logger.info(
                "底库已刷新 [%s]: %d 人 / %d 条向量",
                source,
                person_count,
                vector_count,
            )
        except Exception as exc:
            logger.error("底库刷新失败: %s", exc)

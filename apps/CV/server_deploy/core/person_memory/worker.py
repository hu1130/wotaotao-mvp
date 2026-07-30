"""Durable PostgreSQL-outbox worker for person-memory extraction."""

from __future__ import annotations

import logging
import os
import socket
import threading
import time
import uuid

from config import (
    PERSON_MEMORY_DAILY_SUMMARY_ENABLED,
    PERSON_MEMORY_DAILY_SUMMARY_POLL_SECONDS,
    PERSON_MEMORY_ENABLED,
    PERSON_MEMORY_WORKER_MAX_ATTEMPTS,
    PERSON_MEMORY_WORKER_POLL_SECONDS,
)
from core.person_memory.service import PersonMemoryService

logger = logging.getLogger("person-memory-worker")


class PersonMemoryWorker:
    def __init__(self, service: PersonMemoryService | None = None) -> None:
        self.service = service or PersonMemoryService()
        self.repository = self.service.repository
        self.worker_id = (
            f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
        )
        self._stop_event = threading.Event()
        self._last_daily_summary_scan = 0.0

    def stop(self) -> None:
        self._stop_event.set()

    def run_forever(self) -> None:
        if not PERSON_MEMORY_ENABLED:
            logger.info("人物记忆 worker 已禁用: PERSON_MEMORY_ENABLED=0")
            return
        logger.info("人物记忆 worker 启动: worker=%s", self.worker_id)
        while not self._stop_event.is_set():
            try:
                batch = self.repository.claim_job_batch(self.worker_id)
            except Exception:
                logger.exception("人物记忆任务领取失败")
                self._stop_event.wait(max(0.5, PERSON_MEMORY_WORKER_POLL_SECONDS))
                continue
            if batch is None:
                self._process_due_daily_summaries_if_needed()
                self._stop_event.wait(max(0.2, PERSON_MEMORY_WORKER_POLL_SECONDS))
                continue
            started_at = time.perf_counter()
            try:
                result = self.service.process_job_batch(batch)
                self.repository.complete_jobs(batch.job_ids)
                logger.info(
                    "人物记忆任务完成: jobs=%s person=%s turns=%d result=%s elapsed_ms=%.0f",
                    list(batch.job_ids),
                    _short_person_id(batch.person_id),
                    len(batch.turns),
                    result,
                    (time.perf_counter() - started_at) * 1000,
                )
            except Exception as exc:
                logger.exception(
                    "人物记忆任务失败: jobs=%s person=%s attempt=%d",
                    list(batch.job_ids),
                    _short_person_id(batch.person_id),
                    batch.attempts,
                )
                self.repository.fail_jobs(
                    batch.job_ids,
                    error=f"{type(exc).__name__}: {exc}",
                    attempts=batch.attempts,
                    max_attempts=PERSON_MEMORY_WORKER_MAX_ATTEMPTS,
                )
        logger.info("人物记忆 worker 已停止: worker=%s", self.worker_id)

    def _process_due_daily_summaries_if_needed(self) -> None:
        if not PERSON_MEMORY_DAILY_SUMMARY_ENABLED:
            return
        now = time.monotonic()
        if now - self._last_daily_summary_scan < max(
            5.0, PERSON_MEMORY_DAILY_SUMMARY_POLL_SECONDS
        ):
            return
        self._last_daily_summary_scan = now
        started_at = time.perf_counter()
        try:
            results = self.service.process_due_daily_summaries(limit=5)
        except Exception:
            logger.exception("人物每日总结任务失败")
            return
        if results:
            logger.info(
                "人物每日总结批次完成: count=%d elapsed_ms=%.0f",
                len(results),
                (time.perf_counter() - started_at) * 1000,
            )

    def close(self) -> None:
        self.stop()
        self.service.close()


def _short_person_id(person_id: str) -> str:
    return person_id if len(person_id) <= 16 else f"{person_id[:8]}…{person_id[-6:]}"

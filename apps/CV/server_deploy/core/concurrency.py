"""Reusable concurrency primitives with lightweight runtime metrics."""

from __future__ import annotations

import asyncio
import hashlib
import threading
import time
from contextlib import asynccontextmanager


class CapacityExceeded(RuntimeError):
    def __init__(self, resource: str, scope_key: str) -> None:
        super().__init__(f"{resource} capacity exceeded")
        self.resource = resource
        self.scope_key = scope_key


class StripedLock:
    """Bounded lock registry; unrelated scope keys can run concurrently."""

    def __init__(self, shards: int = 64) -> None:
        self._locks = tuple(threading.RLock() for _ in range(max(1, shards)))

    def for_key(self, key: str) -> threading.RLock:
        digest = hashlib.blake2b(key.encode("utf-8"), digest_size=8).digest()
        index = int.from_bytes(digest, "big") % len(self._locks)
        return self._locks[index]


class AsyncCapacityGate:
    """Fail-fast bounded admission control for expensive async endpoints."""

    def __init__(self, resource: str, limit: int, timeout_seconds: float) -> None:
        self.resource = resource
        self.limit = max(1, int(limit))
        self.timeout_seconds = max(0.0, float(timeout_seconds))
        self._semaphore = asyncio.Semaphore(self.limit)
        self._metrics_lock = threading.Lock()
        self._active = 0
        self._accepted = 0
        self._rejected = 0
        self._total_wait_seconds = 0.0

    @asynccontextmanager
    async def slot(self, scope_key: str):
        started_at = time.perf_counter()
        try:
            if self.timeout_seconds <= 0:
                await asyncio.wait_for(self._semaphore.acquire(), timeout=1e-6)
            else:
                await asyncio.wait_for(
                    self._semaphore.acquire(),
                    timeout=self.timeout_seconds,
                )
        except TimeoutError as exc:
            with self._metrics_lock:
                self._rejected += 1
            raise CapacityExceeded(self.resource, scope_key) from exc

        waited = time.perf_counter() - started_at
        with self._metrics_lock:
            self._active += 1
            self._accepted += 1
            self._total_wait_seconds += waited
        try:
            yield
        finally:
            self._semaphore.release()
            with self._metrics_lock:
                self._active -= 1

    def snapshot(self) -> dict[str, int | float | str]:
        with self._metrics_lock:
            accepted = self._accepted
            return {
                "resource": self.resource,
                "limit": self.limit,
                "active": self._active,
                "accepted": accepted,
                "rejected": self._rejected,
                "averageWaitMs": round(
                    self._total_wait_seconds * 1000 / accepted if accepted else 0.0,
                    3,
                ),
            }

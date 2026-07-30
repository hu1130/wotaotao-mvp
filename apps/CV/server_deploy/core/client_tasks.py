"""In-process task queue for commands that must run on the frontdesk client."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from core.tenant import DEFAULT_TENANT_ID, normalize_tenant_id

logger = logging.getLogger(__name__)


@dataclass
class ClientTask:
    id: str
    action: str
    payload: dict[str, Any]
    tenant_id: str = DEFAULT_TENANT_ID
    target_device_id: str = ""
    required_capabilities: list[str] = field(default_factory=list)
    status: str = "pending"
    created_at: float = field(default_factory=time.time)
    claimed_at: float = 0.0
    finished_at: float = 0.0
    result: dict[str, Any] | None = None
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tenantId": self.tenant_id,
            "action": self.action,
            "payload": self.payload,
            "targetDeviceId": self.target_device_id,
            "requiredCapabilities": self.required_capabilities,
            "status": self.status,
            "createdAt": self.created_at,
            "claimedAt": self.claimed_at,
            "finishedAt": self.finished_at,
            "result": self.result,
            "error": self.error,
        }


class ClientTaskQueue:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._tasks: list[ClientTask] = []

    def create(
        self,
        action: str,
        payload: dict[str, Any] | None = None,
        *,
        target_device_id: str = "",
        required_capabilities: list[str] | None = None,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> ClientTask:
        tenant_id = normalize_tenant_id(tenant_id)
        task = ClientTask(
            id=uuid.uuid4().hex,
            action=action,
            payload=payload or {},
            tenant_id=tenant_id,
            target_device_id=target_device_id.strip(),
            required_capabilities=normalize_required_capabilities(
                action,
                required_capabilities,
            ),
        )
        with self._lock:
            self._tasks.append(task)
            self._prune_locked()
            self._condition.notify_all()
        logger.info(
            "客户端任务已创建: tenant=%s id=%s action=%s target=%s payload=%s",
            task.tenant_id,
            task.id,
            task.action,
            task.target_device_id or "*",
            task.payload,
        )
        return task

    def claim_next(
        self,
        device_id: str = "",
        *,
        supported_actions: list[str] | None = None,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> ClientTask | None:
        tenant_id = normalize_tenant_id(tenant_id)
        now = time.time()
        device_id = (device_id or "").strip()
        supported = {item.strip() for item in supported_actions or [] if item and item.strip()}
        with self._lock:
            self._requeue_stale_locked(now)
            for task in self._tasks:
                if task.status != "pending":
                    continue
                if task.tenant_id != tenant_id:
                    continue
                if task.target_device_id and task.target_device_id != device_id:
                    continue
                missing = [item for item in task.required_capabilities if item not in supported]
                if missing:
                    logger.info(
                        "客户端任务跳过: id=%s action=%s device=%s missing_capabilities=%s supported=%s",
                        task.id,
                        task.action,
                        device_id or "unknown",
                        missing,
                        sorted(supported),
                    )
                    continue
                task.status = "running"
                task.claimed_at = now
                logger.info(
                    "客户端任务已领取: tenant=%s id=%s action=%s device=%s",
                    tenant_id,
                    task.id,
                    task.action,
                    device_id or "unknown",
                )
                return task
        return None

    def complete(
        self,
        task_id: str,
        *,
        ok: bool,
        result: dict[str, Any] | None = None,
        error: str = "",
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> ClientTask | None:
        tenant_id = normalize_tenant_id(tenant_id)
        with self._lock:
            task = self._find_locked(task_id, tenant_id)
            if task is None:
                return None
            task.status = "done" if ok else "failed"
            task.finished_at = time.time()
            task.result = result or {}
            task.error = (error or "")[:2000]
            logger.info(
                "客户端任务完成: id=%s status=%s error=%s result=%s",
                task.id,
                task.status,
                task.error,
                task.result,
            )
            self._condition.notify_all()
            return task

    def stats(self, tenant_id: str = DEFAULT_TENANT_ID) -> dict[str, Any]:
        tenant_id = normalize_tenant_id(tenant_id)
        with self._lock:
            counts: dict[str, int] = {}
            tasks = [task for task in self._tasks if task.tenant_id == tenant_id]
            for task in tasks:
                counts[task.status] = counts.get(task.status, 0) + 1
            return {"tenantId": tenant_id, "total": len(tasks), "counts": counts}

    def get(
        self, task_id: str, tenant_id: str = DEFAULT_TENANT_ID
    ) -> ClientTask | None:
        with self._lock:
            return self._find_locked(task_id, normalize_tenant_id(tenant_id))

    def wait_for_terminal(
        self,
        task_id: str,
        *,
        timeout: float,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> ClientTask | None:
        tenant_id = normalize_tenant_id(tenant_id)
        deadline = time.time() + max(0.0, timeout)
        with self._condition:
            while True:
                task = self._find_locked(task_id, tenant_id)
                if task is None:
                    return None
                if task.status in {"done", "failed"}:
                    return task
                remaining = deadline - time.time()
                if remaining <= 0:
                    return task
                self._condition.wait(timeout=remaining)

    def _find_locked(self, task_id: str, tenant_id: str) -> ClientTask | None:
        for task in self._tasks:
            if task.id == task_id and task.tenant_id == tenant_id:
                return task
        return None

    def _requeue_stale_locked(self, now: float) -> None:
        for task in self._tasks:
            if task.status == "running" and task.claimed_at and now - task.claimed_at > 1800:
                logger.warning("客户端任务运行超时，重新入队: id=%s action=%s", task.id, task.action)
                task.status = "pending"
                task.claimed_at = 0.0

    def _prune_locked(self) -> None:
        if len(self._tasks) <= 200:
            return
        self._tasks = self._tasks[-200:]


_queue = ClientTaskQueue()


def get_client_task_queue() -> ClientTaskQueue:
    return _queue


def normalize_required_capabilities(
    action: str,
    required_capabilities: list[str] | None,
) -> list[str]:
    values = [
        str(item).strip()
        for item in required_capabilities or []
        if str(item).strip()
    ]
    if not values and action == "adjust_system_volume":
        values = ["adjust_system_volume"]
    return sorted(set(values))

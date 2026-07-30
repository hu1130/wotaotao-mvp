"""Process-wide shutdown coordination for the frontdesk client."""

from __future__ import annotations

import logging
import threading

logger = logging.getLogger(__name__)

_shutdown_event = threading.Event()
_shutdown_reason = ""


def request_shutdown(reason: str = "") -> None:
    global _shutdown_reason
    if reason and not _shutdown_reason:
        _shutdown_reason = reason
    if not _shutdown_event.is_set():
        logger.info("客户端退出请求: reason=%s", _shutdown_reason or "unspecified")
        _shutdown_event.set()


def is_shutdown_requested() -> bool:
    return _shutdown_event.is_set()


def wait_for_shutdown(timeout: float | None = None) -> bool:
    return _shutdown_event.wait(timeout)


def shutdown_reason() -> str:
    return _shutdown_reason

"""Debug status persistence for gesture recognition."""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict

from config import GESTURE_STATUS_FILE, GESTURE_STATUS_TTL_SECONDS
from core.gesture.schemas import GestureCandidate, GestureEvent

logger = logging.getLogger(__name__)


class GestureStatusWriter:
    """Writes the latest gesture state for the avatar control panel."""

    def __init__(self, status_file: str = GESTURE_STATUS_FILE) -> None:
        self.status_file = status_file
        self._last_write_at = 0.0
        os.makedirs(os.path.dirname(status_file), exist_ok=True)

    def write(
        self,
        *,
        enabled: bool,
        running: bool,
        stage: str,
        candidate: GestureCandidate | None = None,
        stable_candidate: GestureCandidate | None = None,
        event: GestureEvent | None = None,
        diagnostics: dict | None = None,
        error: str = "",
        force: bool = False,
    ) -> bool:
        now = time.time()
        if not force and now - self._last_write_at < GESTURE_STATUS_TTL_SECONDS:
            return True
        payload = {
            "ok": not bool(error),
            "enabled": enabled,
            "running": running,
            "stage": stage,
            "updatedAt": now,
            "candidate": asdict(candidate) if candidate else None,
            "stableCandidate": asdict(stable_candidate) if stable_candidate else None,
            "event": asdict(event) if event else None,
            "diagnostics": diagnostics or {},
            "error": error,
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        tmp_file = f"{self.status_file}.{os.getpid()}.{time.monotonic_ns()}.tmp"
        try:
            with open(tmp_file, "w", encoding="utf-8") as file:
                file.write(text)
        except OSError as exc:
            logger.debug("手势状态临时文件写入失败: %s", exc)
            return False

        for attempt in range(6):
            try:
                os.replace(tmp_file, self.status_file)
                self._last_write_at = now
                return True
            except PermissionError as exc:
                if attempt == 5:
                    logger.debug("手势状态文件被占用，跳过本次刷新: %s", exc)
                    break
                time.sleep(0.03 * (attempt + 1))
            except OSError as exc:
                logger.debug("手势状态文件刷新失败: %s", exc)
                break

        try:
            os.remove(tmp_file)
        except OSError:
            pass
        return False

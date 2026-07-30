"""File-based camera pause coordination for local OpenCV processes."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from config.common import CACHE_DIR

CONTROL_FILE = Path(CACHE_DIR) / "camera_control.json"
STATUS_FILE = Path(CACHE_DIR) / "camera_status.json"


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def request_camera_pause(owner: str, reason: str = "") -> dict[str, Any]:
    payload = {
        "pause": True,
        "owner": owner,
        "reason": reason,
        "requestedAt": time.time(),
    }
    _atomic_write_json(CONTROL_FILE, payload)
    return payload


def clear_camera_pause(owner: str | None = None) -> None:
    current = _read_json(CONTROL_FILE)
    if owner and current.get("owner") not in ("", owner, None):
        return
    try:
        CONTROL_FILE.unlink()
    except FileNotFoundError:
        pass


def get_camera_pause_request() -> dict[str, Any]:
    data = _read_json(CONTROL_FILE)
    if not data.get("pause"):
        return {}
    return data


def mark_camera_status(status: str, owner: str = "", detail: str = "") -> None:
    _atomic_write_json(
        STATUS_FILE,
        {
            "status": status,
            "owner": owner,
            "detail": detail,
            "updatedAt": time.time(),
        },
    )


def wait_for_camera_released(
    request: dict[str, Any],
    timeout_seconds: float = 8.0,
    poll_seconds: float = 0.2,
) -> bool:
    owner = request.get("owner", "")
    requested_at = float(request.get("requestedAt") or 0.0)
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        status = _read_json(STATUS_FILE)
        if (
            status.get("status") == "released"
            and status.get("owner") == owner
            and float(status.get("updatedAt") or 0.0) >= requested_at
        ):
            return True
        time.sleep(poll_seconds)
    return False

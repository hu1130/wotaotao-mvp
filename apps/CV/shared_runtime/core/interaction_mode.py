"""Runtime interaction mode shared by the avatar frontend and Python services."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config import (
    CACHE_DIR,
    ENABLE_REALTIME_DIALOG,
    REALTIME_DIALOG_RAG_ENABLED,
)


MODE_QUOTES_ONLY = "quotes_only"
MODE_QUOTES_REALTIME = "quotes_realtime"
MODE_QUOTES_REALTIME_RAG = "quotes_realtime_rag"

DEFAULT_MODE_FILE = Path(CACHE_DIR) / "interaction_mode.json"


@dataclass(frozen=True)
class InteractionMode:
    key: str
    label: str
    description: str
    realtime_dialog: bool
    realtime_rag: bool


MODES: dict[str, InteractionMode] = {
    MODE_QUOTES_ONLY: InteractionMode(
        key=MODE_QUOTES_ONLY,
        label="语录",
        description="仅使用人脸识别和固定/随机语录。",
        realtime_dialog=False,
        realtime_rag=False,
    ),
    MODE_QUOTES_REALTIME: InteractionMode(
        key=MODE_QUOTES_REALTIME,
        label="语录+实时",
        description="保留人脸识别语录，同时启用实时语音沟通，不注入知识库。",
        realtime_dialog=True,
        realtime_rag=False,
    ),
    MODE_QUOTES_REALTIME_RAG: InteractionMode(
        key=MODE_QUOTES_REALTIME_RAG,
        label="语录+实时RAG",
        description="保留人脸识别语录，同时启用实时语音和本地知识库检索。",
        realtime_dialog=True,
        realtime_rag=True,
    ),
}


def derive_default_mode() -> str:
    if ENABLE_REALTIME_DIALOG:
        return MODE_QUOTES_REALTIME_RAG if REALTIME_DIALOG_RAG_ENABLED else MODE_QUOTES_REALTIME
    return MODE_QUOTES_ONLY


def normalize_mode(value: str | None) -> str:
    value = (value or "").strip()
    if value in MODES:
        return value
    return derive_default_mode()


def load_interaction_mode(path: Path | None = None) -> str:
    path = path or DEFAULT_MODE_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return derive_default_mode()
    except Exception:
        return derive_default_mode()
    if isinstance(data, dict):
        return normalize_mode(str(data.get("mode") or ""))
    return derive_default_mode()


def save_interaction_mode(mode: str, path: Path | None = None) -> str:
    mode = normalize_mode(mode)
    path = path or DEFAULT_MODE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    payload: dict[str, Any] = {"mode": mode}
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp_path, path)
    return mode

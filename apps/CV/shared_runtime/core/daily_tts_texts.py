"""Daily generated TTS texts with built-in fallback."""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
import threading

from config import (
    DAILY_TTS_TEXTS_FILE,
    DEFAULT_MODEL_KEY,
    MODEL_PROFILES,
    TENANT_DAILY_TTS_TEXTS_DIR,
)
from core.tenant import normalize_tenant_id

logger = logging.getLogger(__name__)
_TEXTS_LOCK = threading.RLock()
_TEXT_POOLS: dict[tuple[str, str, str, bool | None], list[str]] = {}
_LAST_TEXTS: dict[tuple[str, str, str, bool | None], str] = {}
_TENANT_TEXT_CACHE: dict[str, tuple[float, dict[str, dict[str, list[str]]]]] = {}

EVENT_TYPES = {
    "check_in",
    "check_out",
    "stranger",
    "returning_stranger",
    "stranger_stare",
    "repeat",
    "checked_in_stare",
    "first_time",
    "returning",
    "idle_long",
    "crowd",
}


def load_daily_texts() -> dict[str, dict[str, list[str]]]:
    path = Path(DAILY_TTS_TEXTS_FILE)
    if not path.exists():
        return {}

    try:
        with path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as exc:
        logger.warning("每日语录读取失败，使用内置语录: %s", exc)
        return {}

    if payload.get("date") != date.today().isoformat():
        return {}

    texts = payload.get("texts")
    if not isinstance(texts, dict):
        return {}

    if _is_per_model_format(texts):
        return _parse_per_model(texts)

    return _expand_to_per_model(_parse_single(texts))


def tenant_daily_texts_path(tenant_id: str) -> Path:
    tenant_id = normalize_tenant_id(tenant_id)
    return Path(TENANT_DAILY_TTS_TEXTS_DIR) / f"{tenant_id}.json"


def delete_tenant_daily_texts(tenant_id: str) -> bool:
    tenant_id = normalize_tenant_id(tenant_id)
    path = tenant_daily_texts_path(tenant_id)
    deleted = False
    try:
        if path.exists():
            path.unlink()
            deleted = True
    finally:
        invalidate_tenant_daily_texts(tenant_id)
    return deleted


def load_tenant_daily_texts(tenant_id: str) -> dict[str, dict[str, list[str]]]:
    tenant_id = normalize_tenant_id(tenant_id)
    path = tenant_daily_texts_path(tenant_id)
    if not path.exists():
        with _TEXTS_LOCK:
            _TENANT_TEXT_CACHE.pop(tenant_id, None)
        return {}

    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}

    with _TEXTS_LOCK:
        cached = _TENANT_TEXT_CACHE.get(tenant_id)
        if cached and cached[0] == mtime:
            return cached[1]

    try:
        with path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as exc:
        logger.warning("租户每日语录读取失败，使用默认语录: tenant=%s error=%s", tenant_id, exc)
        return {}

    if normalize_tenant_id(str(payload.get("tenant_id") or tenant_id)) != tenant_id:
        return {}
    if payload.get("date") != date.today().isoformat():
        return {}

    texts = payload.get("texts")
    if not isinstance(texts, dict):
        return {}

    parsed = (
        _parse_per_model(texts)
        if _is_per_model_format(texts)
        else _expand_to_per_model(_parse_single(texts))
    )
    with _TEXTS_LOCK:
        _TENANT_TEXT_CACHE[tenant_id] = (mtime, parsed)
    return parsed


def invalidate_tenant_daily_texts(tenant_id: str = "") -> None:
    with _TEXTS_LOCK:
        if tenant_id:
            tenant_id = normalize_tenant_id(tenant_id)
            _TENANT_TEXT_CACHE.pop(tenant_id, None)
            for key in list(_TEXT_POOLS):
                if key[0] == f"tenant:{tenant_id}":
                    _TEXT_POOLS.pop(key, None)
                    _LAST_TEXTS.pop(key, None)
            return
        _TENANT_TEXT_CACHE.clear()
        _TEXT_POOLS.clear()
        _LAST_TEXTS.clear()


def _is_per_model_format(texts: dict) -> bool:
    if not texts:
        return False
    first_value = next(iter(texts.values()), None)
    return isinstance(first_value, dict)


def _parse_per_model(texts: dict) -> dict[str, dict[str, list[str]]]:
    result: dict[str, dict[str, list[str]]] = {}
    for model_key in MODEL_PROFILES:
        model_texts = texts.get(model_key, {})
        if not isinstance(model_texts, dict):
            continue
        parsed = _parse_single(model_texts)
        if parsed:
            result[model_key] = parsed
    return result


def _parse_single(texts: dict) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for event_type in EVENT_TYPES:
        values = texts.get(event_type)
        if not isinstance(values, list):
            continue
        cleaned = [
            _normalize_template(str(value).strip())
            for value in values
            if str(value).strip()
        ]
        if cleaned:
            result[event_type] = cleaned
    return result


def _expand_to_per_model(
    single: dict[str, list[str]],
) -> dict[str, dict[str, list[str]]]:
    return {model_key: dict(single) for model_key in MODEL_PROFILES}


def merge_daily_texts(
    default_texts: dict[str, list[str]],
) -> dict[str, dict[str, list[str]]]:
    daily_texts = load_daily_texts()
    if daily_texts:
        logger.info("已加载今日数字人语录(按角色分组): %s", DAILY_TTS_TEXTS_FILE)
        return daily_texts

    return {model_key: dict(default_texts) for model_key in MODEL_PROFILES}


def refresh_texts(default_texts: dict[str, list[str]], target: dict) -> None:
    merged = merge_daily_texts(default_texts)
    with _TEXTS_LOCK:
        target.clear()
        target.update(merged)
        _TEXT_POOLS.clear()
        _LAST_TEXTS.clear()
        _TENANT_TEXT_CACHE.clear()


def choose_text(
    texts: dict,
    event_type: str,
    require_placeholder: bool | None = None,
    model_key: str = "",
    tenant_id: str = "",
) -> str:
    model_key = model_key or DEFAULT_MODEL_KEY
    tenant_id = normalize_tenant_id(tenant_id) if tenant_id else ""
    if tenant_id:
        text = _choose_from_texts(
            load_tenant_daily_texts(tenant_id),
            event_type,
            require_placeholder,
            model_key,
            f"tenant:{tenant_id}",
        )
        if text:
            return text
    return _choose_from_texts(
        texts,
        event_type,
        require_placeholder,
        model_key,
        "default",
    )


def _choose_from_texts(
    texts: dict,
    event_type: str,
    require_placeholder: bool | None,
    model_key: str,
    source_key: str,
) -> str:
    import random

    model_texts = texts.get(model_key) if isinstance(texts, dict) and model_key else None
    if not isinstance(model_texts, dict):
        for candidate in texts.values() if isinstance(texts, dict) else []:
            if isinstance(candidate, dict):
                model_texts = candidate
                break
    if not isinstance(model_texts, dict):
        return ""

    with _TEXTS_LOCK:
        candidates = _filter_candidates(
            model_texts.get(event_type) or [], require_placeholder
        )
        if not candidates:
            return ""

        pool_key = (source_key, model_key, event_type, require_placeholder)
        pool = _TEXT_POOLS.get(pool_key)
        if not pool or any(item not in candidates for item in pool):
            pool = _reshuffle(candidates, _LAST_TEXTS.get(pool_key), random)
            _TEXT_POOLS[pool_key] = pool

        text = pool.pop()
        _LAST_TEXTS[pool_key] = text
        return text


def _filter_candidates(
    values: list[str], require_placeholder: bool | None
) -> list[str]:
    candidates = list(dict.fromkeys(values))
    if require_placeholder is None:
        return candidates
    return [text for text in candidates if ("{}" in text) == require_placeholder]


def _reshuffle(
    candidates: list[str], last_text: str | None, random_module
) -> list[str]:
    pool = list(candidates)
    random_module.shuffle(pool)
    if len(pool) > 1 and pool[-1] == last_text:
        pool.insert(0, pool.pop())
    return pool


def _normalize_template(value: str) -> str:
    return value.replace("{name}", "{}")

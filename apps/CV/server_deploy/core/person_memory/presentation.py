"""Presentation helpers for person-memory recall text."""

from __future__ import annotations

import re


_TRAILING_PUNCT_RE = re.compile(r"[。.!！?？,，;；、\s]+$")


def recall_summary_topic(summary: str, *, max_chars: int = 140) -> str:
    """Convert an internal daily summary into user-facing recall content."""

    value = _compact(summary)
    if not value:
        return ""
    value = re.sub(r"(?:该用户|当前用户|这位用户|用户)", "你", value)
    value = re.sub(r"(?:前台数字人|数字人|助手|我)\s*(?:主要)?(?:回答|回复|说|提到)了?", "我回答过", value)
    value = _strip_summary_lead(value)
    value = _TRAILING_PUNCT_RE.sub("", value)
    return _clip(value, max_chars=max_chars)


def conversation_topic(text: str, *, max_chars: int = 64) -> str:
    """Keep a turn as a topic phrase instead of a transcript quote."""

    value = _compact(text)
    if not value:
        return ""
    value = _TRAILING_PUNCT_RE.sub("", value)
    return _clip(value, max_chars=max_chars)


def _strip_summary_lead(text: str) -> str:
    value = text
    lead_patterns = (
        r"^(?:我们|你|我)?(?:主要|大概|重点)?(?:聊了|聊到|聊过|讨论了|讨论到|提到|提过|说到|问了|询问了|咨询了|测试了|复盘了)[：:，, ]*",
        r"^你(?:最近|当天|今天|昨天|之前|主要)?(?:在)?",
    )
    changed = True
    while changed:
        changed = False
        for pattern in lead_patterns:
            new_value = re.sub(pattern, "", value)
            if new_value != value:
                value = new_value
                changed = True
    return value.strip("：:，, ")


def _compact(text: str) -> str:
    return " ".join((text or "").split())


def _clip(text: str, *, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max(1, max_chars - 1)].rstrip() + "…"

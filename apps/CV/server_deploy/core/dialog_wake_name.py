"""Assistant wake-name parsing for voice dialog routing."""

from __future__ import annotations

import re
from dataclasses import dataclass

from config import (
    VOICE_ASSISTANT_NAME,
    VOICE_ASSISTANT_WAKE_ALIASES,
    VOICE_ASSISTANT_WAKE_ENABLED,
)


@dataclass(frozen=True)
class WakeNameResult:
    called: bool
    wake_only: bool
    assistant_name: str
    matched_alias: str
    original_text: str
    command_text: str


_LEADING_GREETINGS = (
    "你好",
    "您好",
    "哈喽",
    "hello",
    "hi",
    "嗨",
    "喂",
    "欸",
    "诶",
    "哎",
)
_WAKE_ONLY_PHRASES = {
    "",
    "在吗",
    "你在吗",
    "在不在",
    "你在不在",
    "听得到吗",
    "能听到吗",
    "醒醒",
    "出来一下",
    "来一下",
    "叫你呢",
}
_PUNCT_RE = re.compile(r"^[\s,，.。!！?？:：;；、]+")
_COMPACT_RE = re.compile(r"[\s,，.。!！?？:：;；、~～]+")
_TRAILING_POLITE_RE = re.compile(r"(?:呀|啊|呢|吧|嘛)+$")


def parse_wake_name(
    text: str,
    *,
    assistant_name: str | None = None,
    wake_aliases: tuple[str, ...] | list[str] | None = None,
) -> WakeNameResult:
    original = (text or "").strip()
    if not original or not VOICE_ASSISTANT_WAKE_ENABLED:
        return _miss(original, assistant_name=assistant_name)

    resolved_name = (assistant_name or VOICE_ASSISTANT_NAME).strip() or VOICE_ASSISTANT_NAME
    aliases = sorted(
        set(alias.strip() for alias in (wake_aliases or VOICE_ASSISTANT_WAKE_ALIASES) if alias.strip()),
        key=len,
        reverse=True,
    )
    for candidate in _leading_variants(original):
        for alias in aliases:
            if not candidate.startswith(alias):
                continue
            tail = candidate[len(alias) :]
            command_text = _clean_tail(tail)
            wake_only = _is_wake_only(command_text)
            return WakeNameResult(
                called=True,
                wake_only=wake_only,
                assistant_name=resolved_name,
                matched_alias=alias,
                original_text=original,
                command_text="" if wake_only else command_text,
            )
    return _miss(original, assistant_name=resolved_name)


def _leading_variants(text: str) -> list[str]:
    value = text.strip()
    variants = [value]
    lower_value = value.lower()
    for greeting in _LEADING_GREETINGS:
        if lower_value.startswith(greeting.lower()):
            without_greeting = value[len(greeting) :]
            variants.append(_PUNCT_RE.sub("", without_greeting).strip())
    return [variant for variant in variants if variant]


def _clean_tail(tail: str) -> str:
    value = _PUNCT_RE.sub("", (tail or "").strip())
    if value.startswith("你帮我"):
        value = value[1:]
    return value.strip()


def _is_wake_only(command_text: str) -> bool:
    compact = _COMPACT_RE.sub("", (command_text or "").strip())
    compact = _TRAILING_POLITE_RE.sub("", compact)
    return compact in _WAKE_ONLY_PHRASES


def _miss(original: str, *, assistant_name: str | None = None) -> WakeNameResult:
    return WakeNameResult(
        called=False,
        wake_only=False,
        assistant_name=(assistant_name or VOICE_ASSISTANT_NAME).strip() or VOICE_ASSISTANT_NAME,
        matched_alias="",
        original_text=original,
        command_text=original,
    )

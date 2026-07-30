"""Deterministic voice commands for explicit remember/forget operations."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class PersonMemoryCommand:
    action: str
    content: str = ""
    target_name: str = ""
    exact: bool = False
    repeat: bool = True


_REMEMBER_RE = re.compile(
    r"^(?:请|你)?(?:帮我)?记住(?:一下)?[：:，, ]*(?P<content>.+)$"
)
_FORGET_RE = re.compile(
    r"^(?:请|你)?(?:帮我)?(?:忘掉|忘记|不要再记得)[：:，, ]*(?P<content>.+)$"
)
_CLEAR_RE = re.compile(r"(?:清空|删除|忘掉|忘记).*(?:全部|所有).*(?:个人)?记忆")
_CONFIRM_RE = re.compile(r"^(?:我)?确认(?:删除|忘记|清空)?[。.!！]?$|^(?:是的|确定)[。.!！]?$")
_CANCEL_RE = re.compile(r"^(?:取消|不要删了|算了)[。.!！]?$")
_CANCEL_ARRIVAL_LATEST_RE = re.compile(
    r"^(?:取消|撤销|删除)(?:刚才|上一个|上次|之前|那个)?(?:的)?到场提醒[。.!！]?$"
)
_CANCEL_SELF_ARRIVAL_RE = re.compile(
    r"^(?:以后|之后|往后)?(?:不要|别)(?:再)?"
    r"(?:(?:看见|看到|见到|碰到|遇到)我|我(?:一)?(?:过来|来|出现|回来|到这儿|到这里))"
    r"(?:的时候|以后|之后)?(?:就)?(?:说|讲|喊|提醒我)?(?:这个|这句|这句话)?(?:了)?[。.!！]?$"
)
_QUOTED_TEXT_RE = re.compile(r"[“”\"'‘’](?P<text>[^“”\"'‘’]{1,160})[“”\"'‘’]")
_SELF_ARRIVAL_RE = re.compile(
    r"^(?:(?:我)?(?:说|讲|喊)[：:，, ]*)?(?:以后|之后|往后)?"
    r"(?:"
    r"我(?:一)?(?:过来|来|出现|回来|到这儿|到这里)"
    r"|(?:你)?(?:看见|看到|见到|碰到|遇到)我"
    r")"
    r"(?:的时候|以后|之后)?[：:，, ]*(?:你|我)?(?:就|要|一定要)?"
    r"(?:跟我|对我)?(?:说|讲|喊|提醒我)"
    r"[：:，, ]*(?P<content>.+)$"
)
_TARGET_ARRIVAL_RE = re.compile(
    r"^(?:你)?(?P<timing>以后|之后|往后|待会儿|等会儿|一会儿)?"
    r"(?P<target>[\u4e00-\u9fa5A-Za-z0-9_.·-]{1,32}?)(?:员工|同事|老师|同学|客户|访客)?"
    r"(?:一)?(?:来了|过来|回来|出现|到这儿|到这里|来)"
    r"(?:的时候|以后|之后)?(?:你)?(?:就)?[，,：: ]*(?P<content>.+)$"
)
_INVALID_TARGET_ARRIVAL_NAMES = {
    "我",
    "我要",
    "我是",
    "我们",
    "咱",
    "咱们",
    "你",
    "你要",
    "你是",
    "你们",
    "他",
    "她",
    "它",
    "他们",
    "她们",
    "它们",
}
_TARGET_ARRIVAL_INSTRUCTION_PREFIXES = (
    "跟他说",
    "对他说",
    "跟他讲",
    "对他讲",
    "跟他喊",
    "对他喊",
    "跟她说",
    "对她说",
    "跟她讲",
    "对她讲",
    "跟她喊",
    "对她喊",
    "跟他们说",
    "对他们说",
    "跟她们说",
    "对她们说",
    "提醒他",
    "提醒她",
    "提醒他们",
    "提醒她们",
    "告诉他",
    "告诉她",
    "告诉他们",
    "告诉她们",
    "通知他",
    "通知她",
    "通知他们",
    "通知她们",
    "说",
    "讲",
    "喊",
    "提醒",
    "告诉",
    "通知",
)


def route_person_memory_command(text: str) -> PersonMemoryCommand | None:
    query = " ".join((text or "").strip().split())
    if not query:
        return None
    if _CONFIRM_RE.fullmatch(query):
        return PersonMemoryCommand("confirm_forget")
    if _CANCEL_RE.fullmatch(query):
        return PersonMemoryCommand("cancel_forget")
    if _CANCEL_ARRIVAL_LATEST_RE.fullmatch(query):
        return PersonMemoryCommand("cancel_arrival_task", content="latest")
    if _CANCEL_SELF_ARRIVAL_RE.fullmatch(query):
        return PersonMemoryCommand("cancel_arrival_task", content="self")
    if _CLEAR_RE.search(query):
        return PersonMemoryCommand("request_clear")
    arrival = _route_arrival_task(query)
    if arrival is not None:
        return arrival
    remember = _REMEMBER_RE.fullmatch(query)
    if remember:
        content = remember.group("content").strip()
        arrival = _route_arrival_task(content)
        if arrival is not None:
            return arrival
        return PersonMemoryCommand("remember", content)
    forget = _FORGET_RE.fullmatch(query)
    if forget:
        content = forget.group("content").strip()
        if content:
            return PersonMemoryCommand("request_forget", content)
    return None


def _route_arrival_task(query: str) -> PersonMemoryCommand | None:
    self_match = _SELF_ARRIVAL_RE.fullmatch(query)
    if self_match:
        content, exact = _arrival_content(self_match.group("content"))
        if content:
            return PersonMemoryCommand(
                "arrival_task",
                content=content,
                target_name="",
                exact=exact,
                repeat=True,
            )

    target_match = _TARGET_ARRIVAL_RE.fullmatch(query)
    if not target_match:
        return None
    target_name = target_match.group("target").strip()
    timing = target_match.group("timing") or ""
    raw_content = target_match.group("content")
    if not _is_valid_target_arrival(target_name, raw_content, timing=timing):
        return None
    content, exact = _arrival_content(raw_content)
    if not content:
        return None
    return PersonMemoryCommand(
        "arrival_task",
        content=content,
        target_name=target_name,
        exact=exact,
        repeat=timing not in {"待会儿", "等会儿", "一会儿"},
    )


def _arrival_content(raw: str) -> tuple[str, bool]:
    value = " ".join((raw or "").strip().split())[:240]
    if not value:
        return "", False
    quoted = _QUOTED_TEXT_RE.search(value)
    if quoted:
        return quoted.group("text").strip(), True
    for prefix in (
        "跟我说",
        "对我说",
        "跟我喊",
        "对我喊",
        "跟他说",
        "对他说",
        "跟他喊",
        "对他喊",
        "跟她说",
        "对她说",
        "跟她喊",
        "对她喊",
        "说",
        "讲",
        "喊",
        "提醒我",
        "提醒他",
        "提醒她",
    ):
        if value.startswith(prefix):
            value = value[len(prefix) :].lstrip("：:，, ")
            break
    return _normalize_unquoted_arrival_content(value)[:200], False


def _is_valid_target_arrival(target_name: str, raw_content: str, *, timing: str) -> bool:
    target = (target_name or "").strip()
    if not target or target in _INVALID_TARGET_ARRIVAL_NAMES:
        return False
    if target.startswith(("我", "你", "咱")):
        return False
    if timing:
        return True
    content = " ".join((raw_content or "").strip().split())
    return bool(content) and content.startswith(_TARGET_ARRIVAL_INSTRUCTION_PREFIXES)


def _normalize_unquoted_arrival_content(value: str) -> str:
    value = " ".join((value or "").strip().split())
    if not value:
        return ""
    if re.fullmatch(r"[A-Za-z0-9\s？?！!。.,，、;；:'\"’‘-]+", value):
        value = re.sub(r"[？?！!。.,，、;；]+", " ", value)
        value = " ".join(value.split())
    return value

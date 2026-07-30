"""Command intents embedded in browser voice dialog."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from core.dialog_actions import ACTION_CAPTURE_FACE_ENROLL, DialogActionExecutor, DialogActionProposal

logger = logging.getLogger(__name__)


FACE_CAPTURE_ACTION = ACTION_CAPTURE_FACE_ENROLL
FACE_CAPTURE_PATTERNS = [
    "录人脸",
    "路人脸",
    "录入人脸",
    "路入人脸",
    "注册人脸",
    "采集人脸",
    "添加人脸",
    "新增人脸",
    "登记人脸",
    "录一下人脸",
    "路一下人脸",
    "录个人脸",
    "录脸",
    "路脸",
    "录一下脸",
    "路一下脸",
    "录个脸",
    "人脸建档",
    "人脸录入",
    "人脸注册",
    "人脸采集",
    "人脸登记",
    "人脸添加",
]
FACE_CAPTURE_COMMAND_RE = re.compile(
    r"(?:录入|录|注册|采集|添加|新增|登记|建档)(?:一下|个|个人)?(?:人脸|脸)"
    r"|人脸(?:录入|注册|采集|添加|新增|登记|建档)"
    r"|(?:录入|录|注册|采集|添加|新增|登记|建档)[\u4e00-\u9fffA-Za-z0-9_·]{2,16}的人脸"
)


@dataclass(frozen=True)
class DialogCommandResult:
    handled: bool
    response: str = ""
    command: str = ""
    task_id: str = ""
    payload: dict | None = None


class DialogCommandRouter:
    def route(self, text: str) -> DialogActionProposal | None:
        query = normalize_command_text(text)
        if not query:
            return None
        if not is_face_capture_command(query):
            if maybe_face_capture_like(query):
                logger.warning("疑似人脸录入命令未命中: raw=%s normalized=%s", text, query)
            return None
        name = extract_face_capture_name(query)
        logger.info(
            "语音高置信命令命中: action=%s name=%s raw=%s normalized=%s",
            FACE_CAPTURE_ACTION,
            name or "(need_prompt)",
            text,
            query,
        )
        return DialogActionProposal(
            action=FACE_CAPTURE_ACTION,
            confidence=0.98,
            params={"name": name},
            source="command_router",
            reason="face_capture_keyword",
        )

    def handle(self, text: str) -> DialogCommandResult:
        proposal = self.route(text)
        if proposal is None:
            return DialogCommandResult(False)
        execution = DialogActionExecutor().execute(
            proposal,
            user_text=text,
            conversation_id="legacy-dialog-command",
        )
        return DialogCommandResult(
            execution.handled,
            response=execution.response,
            command=execution.action,
            task_id=execution.task_id,
            payload=execution.payload,
        )


def normalize_command_text(text: str) -> str:
    text = re.sub(r"\s+", "", (text or "").strip())
    replacements = {
        "人怜": "人脸",
        "路入人脸": "录入人脸",
        "路一下人脸": "录一下人脸",
        "路人脸": "录人脸",
        "路脸": "录脸",
        "路一下脸": "录一下脸",
        "录一下脸": "录一下人脸",
        "录个脸": "录个人脸",
        "录脸": "录人脸",
        "添加人脸": "录人脸",
        "新增人脸": "录人脸",
        "登记人脸": "录人脸",
        "人脸建档": "录人脸",
        "人脸登记": "人脸录入",
        "人脸添加": "人脸录入",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return text


def is_face_capture_command(text: str) -> bool:
    return bool(FACE_CAPTURE_COMMAND_RE.search(text))


def maybe_face_capture_like(text: str) -> bool:
    return any(keyword in text for keyword in {"人脸", "人怜", "录脸", "路脸", "注册", "录入", "采集"})


def extract_face_capture_name(text: str) -> str:
    cleaned = re.sub(
        r"^(?:麻烦|帮忙|请|可以|能不能|帮我|给我|我要|我想|现在|马上)+",
        "",
        text,
    )
    candidates = [
        r"(?:给|帮|为|替|把)(?P<name>[\u4e00-\u9fffA-Za-z0-9_·]{1,16})(?:录入|录|注册|采集|添加|登记|建档)(?:一下|个)?人脸",
        r"(?P<name>[\u4e00-\u9fffA-Za-z0-9_·]{2,16})(?:录入|录|注册|采集|添加|登记|建档)(?:一下|个)?人脸",
        r"(?:录入|录|注册|采集|添加|登记|建档)(?P<name>[\u4e00-\u9fffA-Za-z0-9_·]{2,16})的人脸",
    ]
    for pattern in candidates:
        match = re.search(pattern, cleaned)
        if not match:
            continue
        name = normalize_employee_name(match.group("name"))
        if name:
            return name
    return ""


def normalize_employee_name(name: str) -> str:
    name = re.sub(r"[，。！？,.!?;；:：、\s]+", "", name or "")
    name = re.sub(r"^(给|帮|把|为)", "", name)
    name = re.sub(r"(员工|同事|人脸)$", "", name)
    if name in {"我", "自己", "本人", "新人", "员工", "录", "录入", "路", "路入", "录人脸", "路人脸"}:
        return ""
    return name[:32]

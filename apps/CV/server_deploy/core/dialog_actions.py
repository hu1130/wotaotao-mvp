"""Voice action routing, execution, and hidden agent signals."""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

from config import VOICE_AGENT_INTENT_MIN_CONFIDENCE, VOICE_AGENT_INTENT_ROUTER_ENABLED
from core.agent_signal_bus import AgentSignalBus
from core.client_tasks import get_client_task_queue
from core.tenant import DEFAULT_TENANT_ID, normalize_tenant_id

logger = logging.getLogger(__name__)


ACTION_CAPTURE_FACE_ENROLL = "capture_face_enroll"
ACTION_ADJUST_VOLUME = "adjust_volume"
ACTION_ADJUST_SYSTEM_VOLUME = "adjust_system_volume"
ACTION_CLARIFY_VOLUME_DIRECTION = "clarify_volume_direction"

EXECUTED = "executed"
UNSUPPORTED = "unsupported"
REJECTED = "rejected"
INPUT_REQUIRED = "input_required"


@dataclass(frozen=True)
class DialogActionProposal:
    action: str
    confidence: float
    params: dict[str, Any] = field(default_factory=dict)
    source: str = ""
    reason: str = ""
    requires_confirmation: bool = False

    @property
    def accepted(self) -> bool:
        return bool(self.action) and self.confidence >= VOICE_AGENT_INTENT_MIN_CONFIDENCE


@dataclass(frozen=True)
class DialogActionExecution:
    handled: bool
    status: str
    response: str
    action: str = ""
    task_id: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    agent_signal: dict[str, Any] | None = None


class DialogActionExecutor:
    """The only place where voice tool proposals become real side effects."""

    def __init__(self, signal_bus: AgentSignalBus | None = None) -> None:
        self.signal_bus = signal_bus or AgentSignalBus()

    def execute(
        self,
        proposal: DialogActionProposal,
        *,
        user_text: str,
        conversation_id: str,
        device_id: str = "",
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> DialogActionExecution:
        tenant_id = normalize_tenant_id(tenant_id)
        if not proposal.accepted:
            logger.info(
                "语音动作建议被拒绝: action=%s confidence=%.2f min=%.2f reason=%s text=%s",
                proposal.action,
                proposal.confidence,
                VOICE_AGENT_INTENT_MIN_CONFIDENCE,
                proposal.reason,
                user_text,
            )
            return DialogActionExecution(
                handled=False,
                status=REJECTED,
                response="",
                action=proposal.action,
            )

        if proposal.action == ACTION_CAPTURE_FACE_ENROLL:
            return self._execute_face_capture(
                proposal,
                user_text=user_text,
                conversation_id=conversation_id,
                device_id=device_id,
                tenant_id=tenant_id,
            )

        if proposal.action == ACTION_ADJUST_VOLUME:
            return self._execute_volume_adjustment(
                proposal,
                user_text=user_text,
                conversation_id=conversation_id,
                device_id=device_id,
                tenant_id=tenant_id,
            )

        if proposal.action == ACTION_ADJUST_SYSTEM_VOLUME:
            return self._execute_system_volume_adjustment(
                proposal,
                user_text=user_text,
                conversation_id=conversation_id,
                device_id=device_id,
                tenant_id=tenant_id,
            )

        if proposal.action == ACTION_CLARIFY_VOLUME_DIRECTION:
            return self._execute_volume_direction_clarification(
                proposal,
                user_text=user_text,
                conversation_id=conversation_id,
                device_id=device_id,
                tenant_id=tenant_id,
            )

        return self._unsupported_action(
            proposal,
            user_text=user_text,
            conversation_id=conversation_id,
            device_id=device_id,
            tenant_id=tenant_id,
            response="我理解你想让我执行一个操作，但这个动作暂时还没有接入。",
        )

    def _execute_face_capture(
        self,
        proposal: DialogActionProposal,
        *,
        user_text: str,
        conversation_id: str,
        device_id: str,
        tenant_id: str,
    ) -> DialogActionExecution:
        name = str(proposal.params.get("name") or "").strip()
        if not name:
            response = "好的，请在屏幕上输入员工姓名，提交后我再打开人脸录入。"
            payload = {
                "name": "",
                "source": proposal.source or "voice_action",
                "rawText": user_text,
                "requiresBrowserInput": True,
                "inputKind": "face_capture_employee_name",
            }
            signal = self._build_signal(
                proposal,
                user_text=user_text,
                conversation_id=conversation_id,
                device_id=device_id,
                tenant_id=tenant_id,
                status=INPUT_REQUIRED,
                facts={"employee_name": "", "input_kind": payload["inputKind"]},
                target_agents=["frontdesk_agent"],
            )
            self.signal_bus.publish(signal)
            logger.info(
                "语音动作等待浏览器补充姓名: action=%s source=%s confidence=%.2f device=%s",
                ACTION_CAPTURE_FACE_ENROLL,
                proposal.source,
                proposal.confidence,
                device_id or "(unknown)",
            )
            return DialogActionExecution(
                handled=True,
                status=INPUT_REQUIRED,
                response=response,
                action=ACTION_CAPTURE_FACE_ENROLL,
                payload=payload,
                agent_signal=signal,
            )

        task = get_client_task_queue().create(
            ACTION_CAPTURE_FACE_ENROLL,
            {
                "name": name,
                "source": proposal.source or "voice_action",
                "rawText": user_text,
            },
            target_device_id=device_id,
            tenant_id=normalize_tenant_id(tenant_id),
        )
        logger.info(
            "语音动作执行: action=%s task=%s name=%s source=%s confidence=%.2f",
            ACTION_CAPTURE_FACE_ENROLL,
            task.id,
            name or "(need_prompt)",
            proposal.source,
            proposal.confidence,
        )
        if name:
            response = f"好的，我马上为{name}打开人脸录入，请看摄像头提示。"
        else:
            response = "好的，我马上打开人脸录入。请在弹窗里输入员工姓名，然后按提示看向摄像头。"

        signal = self._build_signal(
            proposal,
            user_text=user_text,
            conversation_id=conversation_id,
            device_id=device_id,
            tenant_id=tenant_id,
            status=EXECUTED,
            facts={"employee_name": name, "task_id": task.id},
            target_agents=["frontdesk_agent", "memory_agent"],
        )
        self.signal_bus.publish(signal)
        return DialogActionExecution(
            handled=True,
            status=EXECUTED,
            response=response,
            action=ACTION_CAPTURE_FACE_ENROLL,
            task_id=task.id,
            payload=task.payload,
            agent_signal=signal,
        )

    def _unsupported_action(
        self,
        proposal: DialogActionProposal,
        *,
        user_text: str,
        conversation_id: str,
        device_id: str,
        tenant_id: str,
        response: str,
    ) -> DialogActionExecution:
        logger.info(
            "语音动作暂未支持: action=%s source=%s confidence=%.2f text=%s",
            proposal.action,
            proposal.source,
            proposal.confidence,
            user_text,
        )
        signal = self._build_signal(
            proposal,
            user_text=user_text,
            conversation_id=conversation_id,
            device_id=device_id,
            tenant_id=tenant_id,
            status=UNSUPPORTED,
            facts=proposal.params,
            target_agents=["frontdesk_agent"],
        )
        self.signal_bus.publish(signal)
        return DialogActionExecution(
            handled=True,
            status=UNSUPPORTED,
            response=response,
            action=proposal.action,
            payload=proposal.params,
            agent_signal=signal,
        )

    def _execute_volume_adjustment(
        self,
        proposal: DialogActionProposal,
        *,
        user_text: str,
        conversation_id: str,
        device_id: str,
        tenant_id: str,
    ) -> DialogActionExecution:
        params = normalize_volume_params(proposal.params)
        direction = params.get("direction") or "set"
        delta = params.get("delta")
        level = params.get("level")
        response_style = params.get("response_style")
        if response_style == "now_check":
            response = "现在呢？"
        elif response_style == "ask_check":
            response = "你看看这个音量怎么样。"
        elif direction == "increase":
            response = "好的，音量调高一点。"
        elif direction == "decrease":
            response = "好的，音量调低一点。"
        elif direction == "mute":
            response = "好的，我先把声音静音。"
        elif level is not None:
            response = f"好的，音量调整到{int(level * 100)}%。"
        else:
            response = "好的，我来调整音量。"

        logger.info(
            "语音动作执行: action=%s direction=%s delta=%s level=%s source=%s confidence=%.2f",
            ACTION_ADJUST_VOLUME,
            direction,
            delta,
            level,
            proposal.source,
            proposal.confidence,
        )
        signal = self._build_signal(
            proposal,
            user_text=user_text,
            conversation_id=conversation_id,
            device_id=device_id,
            tenant_id=tenant_id,
            status=EXECUTED,
            facts=params,
            target_agents=["frontdesk_agent"],
        )
        self.signal_bus.publish(signal)
        return DialogActionExecution(
            handled=True,
            status=EXECUTED,
            response=response,
            action=ACTION_ADJUST_VOLUME,
            payload=params,
            agent_signal=signal,
        )

    def _execute_system_volume_adjustment(
        self,
        proposal: DialogActionProposal,
        *,
        user_text: str,
        conversation_id: str,
        device_id: str,
        tenant_id: str,
    ) -> DialogActionExecution:
        params = normalize_volume_params(proposal.params)
        task = get_client_task_queue().create(
            ACTION_ADJUST_SYSTEM_VOLUME,
            {
                **params,
                "source": proposal.source or "voice_action",
                "rawText": user_text,
            },
            target_device_id=device_id,
            tenant_id=normalize_tenant_id(tenant_id),
        )
        direction = params.get("direction") or "set"
        level = params.get("level")
        response_style = params.get("response_style")
        if response_style == "now_check":
            response = "现在呢？"
        elif response_style == "ask_check":
            response = "你看看这个音量怎么样。"
        elif direction == "increase":
            response = "好的，我让前台设备把系统音量调高一点。"
        elif direction == "decrease":
            response = "好的，我让前台设备把系统音量调低一点。"
        elif direction == "mute":
            response = "好的，我让前台设备静音。"
        elif level is not None:
            response = f"好的，我让前台设备把系统音量调到{int(level * 100)}%。"
        else:
            response = "好的，我让前台设备调整系统音量。"
        logger.info(
            "语音动作执行: action=%s task=%s direction=%s payload=%s source=%s confidence=%.2f",
            ACTION_ADJUST_SYSTEM_VOLUME,
            task.id,
            direction,
            task.payload,
            proposal.source,
            proposal.confidence,
        )
        signal = self._build_signal(
            proposal,
            user_text=user_text,
            conversation_id=conversation_id,
            device_id=device_id,
            tenant_id=tenant_id,
            status=EXECUTED,
            facts={"task_id": task.id, **params},
            target_agents=["frontdesk_agent"],
        )
        self.signal_bus.publish(signal)
        return DialogActionExecution(
            handled=True,
            status=EXECUTED,
            response=response,
            action=ACTION_ADJUST_SYSTEM_VOLUME,
            task_id=task.id,
            payload=task.payload,
            agent_signal=signal,
        )

    def _execute_volume_direction_clarification(
        self,
        proposal: DialogActionProposal,
        *,
        user_text: str,
        conversation_id: str,
        device_id: str,
        tenant_id: str,
    ) -> DialogActionExecution:
        logger.info(
            "语音动作需要澄清: action=%s source=%s confidence=%.2f text=%s",
            ACTION_CLARIFY_VOLUME_DIRECTION,
            proposal.source,
            proposal.confidence,
            user_text,
        )
        signal = self._build_signal(
            proposal,
            user_text=user_text,
            conversation_id=conversation_id,
            device_id=device_id,
            tenant_id=tenant_id,
            status=EXECUTED,
            facts=proposal.params,
            target_agents=["frontdesk_agent"],
        )
        self.signal_bus.publish(signal)
        return DialogActionExecution(
            handled=True,
            status=EXECUTED,
            response="你想让我把声音调大一点，还是调小一点？",
            action=ACTION_CLARIFY_VOLUME_DIRECTION,
            payload=proposal.params,
            agent_signal=signal,
        )

    def _build_signal(
        self,
        proposal: DialogActionProposal,
        *,
        user_text: str,
        conversation_id: str,
        device_id: str,
        tenant_id: str,
        status: str,
        facts: dict[str, Any],
        target_agents: list[str],
    ) -> dict[str, Any]:
        return {
            "type": "agent_signal",
            "source": "voice_api",
            "tenant_id": normalize_tenant_id(tenant_id),
            "conversation_id": conversation_id,
            "device_id": device_id,
            "intent": proposal.action,
            "confidence": round(proposal.confidence, 3),
            "status": status,
            "user_text": user_text,
            "facts": facts,
            "target_agents": target_agents,
            "visibility": "internal",
            "created_at": time.time(),
            "router": proposal.source,
            "reason": proposal.reason,
        }


class DialogAgentIntentRouter:
    """Lightweight tool-intent layer before normal chat generation.

    This module is intentionally separate from the direct command router. It is
    the expansion point for an LLM-backed agent classifier, while keeping actual
    side effects behind DialogActionExecutor.
    """

    def route(self, text: str, context: list[dict] | None = None) -> DialogActionProposal | None:
        if not VOICE_AGENT_INTENT_ROUTER_ENABLED:
            return None

        query = normalize_action_text(text)
        if not query:
            return None

        followup = detect_volume_followup_action(query, context)
        if followup:
            action = ACTION_ADJUST_VOLUME if followup.get("target") == "web" else ACTION_ADJUST_SYSTEM_VOLUME
            logger.info("语音 Agent 意图命中音量追问动作: text=%s params=%s", text, followup)
            return DialogActionProposal(
                action=action,
                confidence=0.9,
                params=followup,
                source="agent_intent_router",
                reason="volume_direction_clarification_followup",
            )

        if not looks_like_tool_intent(query):
            logger.debug("语音 Agent 意图跳过普通聊天: text=%s", text)
            return None

        volume = detect_volume_action(query)
        if volume:
            if is_ambiguous_volume_action(volume):
                logger.info("语音 Agent 意图需要澄清音量方向: text=%s params=%s", text, volume)
                return DialogActionProposal(
                    action=ACTION_CLARIFY_VOLUME_DIRECTION,
                    confidence=0.86,
                    params=volume,
                    source="agent_intent_router",
                    reason="ambiguous_volume_direction",
                )
            action = ACTION_ADJUST_VOLUME if is_web_volume_intent(query) else ACTION_ADJUST_SYSTEM_VOLUME
            logger.info("语音 Agent 意图命中音量动作: text=%s params=%s", text, volume)
            return DialogActionProposal(
                action=action,
                confidence=0.88,
                params=volume,
                source="agent_intent_router",
                reason="web_volume_tool_intent" if action == ACTION_ADJUST_VOLUME else "system_volume_tool_intent",
            )

        if maybe_face_capture_intent(query):
            logger.info("语音 Agent 意图补位人脸录入: text=%s", text)
            return DialogActionProposal(
                action=ACTION_CAPTURE_FACE_ENROLL,
                confidence=0.82,
                params={"name": ""},
                source="agent_intent_router",
                reason="face_capture_tool_intent",
            )

        logger.info("语音 Agent 意图未形成可执行动作: text=%s", text)
        return None


def normalize_action_text(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").strip())


def looks_like_tool_intent(text: str) -> bool:
    keywords = {
        "录",
        "注册",
        "登记",
        "采集",
        "添加",
        "建档",
        "调",
        "音量",
        "声音",
        "声大",
        "声小",
        "声太大",
        "声太小",
        "大声",
        "小声",
        "静音",
        "打开",
        "关闭",
        "切换",
    }
    return any(keyword in text for keyword in keywords)


def detect_volume_action(text: str) -> dict[str, Any] | None:
    if not any(keyword in text for keyword in {"音量", "声音", "声大", "声小", "声太大", "声太小", "大声", "小声", "静音"}):
        return None
    if "静音" in text:
        logger.debug("语音音量识别跳过静音词，静音只由业务静音控制处理: text=%s", text)
        return None
    if any(
        keyword in text
        for keyword in {
            "调高",
            "提高",
            "升高",
            "增大",
            "加大",
            "大点",
            "大一点",
            "高点",
            "高一点",
            "高音量",
            "音量高",
            "大声",
            "声音大",
            "声音大点",
            "声音大一点",
            "声音太小",
            "声大",
            "声大点",
            "声大一点",
            "声太小",
            "音量太小",
            "太小了",
            "太小",
            "不够",
            "不够大",
        }
    ):
        return {"direction": "increase", "delta": 10, "response_style": "ask_check"}
    if any(
        keyword in text
        for keyword in {
            "调低",
            "降低",
            "减小",
            "小点",
            "小一点",
            "低点",
            "低一点",
            "小声",
            "声音小",
            "声音小点",
            "声音小一点",
            "声小",
            "声小点",
            "声小一点",
            "声太大",
            "低音量",
            "音量低",
            "音量小",
            "小音量",
        }
    ):
        return {"direction": "decrease", "delta": 10, "response_style": "ask_check"}
    if "静音" in text:
        return {"direction": "mute"}
    if not _has_ambiguous_volume_control_intent(text):
        return None
    return {"direction": "set", "raw": text}


def is_ambiguous_volume_action(params: dict[str, Any]) -> bool:
    return str(params.get("direction") or "") == "set" and "level" not in params


def _has_ambiguous_volume_control_intent(text: str) -> bool:
    return any(
        keyword in text
        for keyword in {
            "调音量",
            "调一下音量",
            "调整音量",
            "调整一下音量",
            "设置一下音量",
            "设置音量",
            "改音量",
            "把音量",
            "将音量",
            "调声音",
            "调一下声音",
            "调整声音",
            "调整一下声音",
            "设置一下声音",
            "设置声音",
            "改声音",
            "把声音",
            "将声音",
            "调大调小",
            "大声点小声点",
        }
    )


def is_system_volume_intent(text: str) -> bool:
    return any(keyword in text for keyword in {"系统音量", "电脑音量", "设备音量", "主音量", "windows音量", "Windows音量"})


def is_web_volume_intent(text: str) -> bool:
    return any(keyword in text for keyword in {"网页音量", "浏览器音量", "数字人音量", "页面音量", "avatar音量", "Avatar音量"})


def detect_volume_followup_action(text: str, context: list[dict] | None) -> dict[str, Any] | None:
    if not is_recent_volume_check_context(context):
        return None
    target = recent_volume_target(context)
    if any(keyword in text for keyword in {"太小", "不够", "不够大", "还是小", "再大", "再高", "大一点", "大点", "听不清"}):
        return {
            "direction": "increase",
            "delta": 10,
            "response_style": "now_check",
            "target": target,
        }
    if any(keyword in text for keyword in {"太大", "太吵", "吵", "大了", "过大", "小一点", "小点", "低一点", "低点"}):
        return {
            "direction": "decrease",
            "delta": 10,
            "response_style": "now_check",
            "target": target,
        }
    return None


def is_recent_volume_check_context(context: list[dict] | None) -> bool:
    for item in reversed(context or []):
        role = str(item.get("role") or "")
        content = str(item.get("content") or "")
        if role == "assistant" and (
            ("调大" in content and "调小" in content)
            or ("大一点" in content and "小一点" in content and "声音" in content)
        ):
            return True
        if role == "assistant" and ("音量怎么样" in content or "现在呢" in content):
            return True
        if role == "user" and any(keyword in content for keyword in {"人脸", "录入", "注册"}):
            return False
    return False


def recent_volume_target(context: list[dict] | None) -> str:
    for item in reversed(context or []):
        content = str(item.get("content") or "")
        if "网页音量" in content or "数字人音量" in content:
            return "web"
        if "系统音量" in content or "前台设备" in content or "音量怎么样" in content:
            return "system"
    return "system"


def normalize_volume_params(params: dict[str, Any] | None) -> dict[str, Any]:
    params = dict(params or {})
    direction = str(params.get("direction") or "set").strip().lower()
    if direction not in {"increase", "decrease", "mute", "set"}:
        direction = "set"
    normalized: dict[str, Any] = {"direction": direction}
    if direction in {"increase", "decrease"}:
        try:
            delta = int(params.get("delta") or 10)
        except (TypeError, ValueError):
            delta = 10
        normalized["delta"] = max(1, min(50, delta))
    if direction == "mute":
        normalized["level"] = 0.0
    elif "level" in params:
        try:
            normalized["level"] = max(0.0, min(1.0, float(params["level"])))
        except (TypeError, ValueError):
            pass
    if "raw" in params:
        normalized["raw"] = str(params["raw"])[:120]
    if "response_style" in params:
        style = str(params["response_style"])
        if style in {"ask_check", "now_check"}:
            normalized["response_style"] = style
    if "target" in params:
        target = str(params["target"])
        if target in {"system", "web"}:
            normalized["target"] = target
    return normalized


def maybe_face_capture_intent(text: str) -> bool:
    return "人脸" in text and any(keyword in text for keyword in {"录", "注册", "登记", "采集", "添加", "建档"})

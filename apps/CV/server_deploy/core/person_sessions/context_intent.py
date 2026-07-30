"""Trusted person-context intents for an active conversation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from core.dialog_intent_router import (
    ConversationRecallIntent,
    is_conversation_recall_query,
    is_self_identity_query,
    parse_conversation_recall_intent,
)
from core.person_memory.presentation import conversation_topic, recall_summary_topic


PERSON_IDENTITY_INTENT = "person_identity"
CONVERSATION_RECALL_INTENT = "conversation_recall"


@dataclass(frozen=True)
class PersonContextReply:
    intent: str
    text: str
    identity_verified: bool
    source_messages: int = 0
    needs_clarification: bool = False
    required_facts: tuple[str, ...] = ()
    response_goal: str = ""
    constraints: tuple[str, ...] = ()


class PersonContextIntentRouter:
    """Resolve answers that must come from server-owned person context."""

    def route(
        self,
        text: str,
        *,
        person_name: str,
        identity_verified: bool,
        context: Sequence[dict[str, Any]] | None = None,
        dated_recall: Mapping[str, Any] | None = None,
    ) -> PersonContextReply | None:
        if is_self_identity_query(text):
            return self._identity_reply(
                person_name=person_name,
                identity_verified=identity_verified,
            )

        recall_intent = parse_conversation_recall_intent(text)
        if recall_intent.matched or recall_intent.needs_clarification:
            return self._conversation_recall_reply(
                recall_intent=recall_intent,
                identity_verified=identity_verified,
                context=context or (),
                dated_recall=dated_recall,
            )

        return None

    @staticmethod
    def _identity_reply(
        *,
        person_name: str,
        identity_verified: bool,
    ) -> PersonContextReply:
        name = (person_name or "").strip()
        if identity_verified and name:
            return PersonContextReply(
                intent=PERSON_IDENTITY_INTENT,
                text="当前用户身份已确认。",
                identity_verified=True,
                required_facts=(
                    f"当前用户身份已通过服务端可信识别确认，姓名：{name}。",
                ),
                response_goal=(
                    "回答用户是否知道或认识他。可以自然说出姓名，但不要每次固定说"
                    "“知道，你是...”或“当然认识...”。"
                ),
                constraints=(
                    "只使用服务端已验证姓名，不要使用客户端自报姓名。",
                    "不要声称知道未提供的身份、职位、关系或历史细节。",
                    "不要固定以“当然认识”“知道”“记得”开头。",
                ),
            )

        return PersonContextReply(
            intent=PERSON_IDENTITY_INTENT,
            text="当前用户身份尚未确认。",
            identity_verified=False,
            required_facts=(
                "当前用户身份尚未通过服务端可信识别确认。",
                "不能读取或透露个人身份和个人记忆。",
                "可以提示用户正对摄像头停留一下完成识别。",
            ),
            response_goal="自然说明现在还不能确认用户是谁，并给出下一步提示。",
            constraints=(
                "不要使用客户端传入的未验证姓名。",
                "不要假装认识用户。",
            ),
        )

    @staticmethod
    def _conversation_recall_reply(
        *,
        recall_intent: ConversationRecallIntent,
        identity_verified: bool,
        context: Sequence[dict[str, Any]],
        dated_recall: Mapping[str, Any] | None = None,
    ) -> PersonContextReply:
        if recall_intent.needs_clarification:
            return PersonContextReply(
                intent=CONVERSATION_RECALL_INTENT,
                text="对话回忆请求需要澄清。",
                identity_verified=identity_verified,
                needs_clarification=True,
                required_facts=(
                    _conversation_recall_clarification(recall_intent),
                    "这是澄清问题，不要读取或复述历史记录。",
                ),
                response_goal="向用户确认他是不是想让你回忆之前的对话。",
                constraints=(
                    "只提出澄清问题，不要编造历史对话内容。",
                    "不要固定以“记得”开头。",
                ),
            )

        if not identity_verified:
            return PersonContextReply(
                intent=CONVERSATION_RECALL_INTENT,
                text="当前用户身份尚未确认，不能读取个人对话记录。",
                identity_verified=False,
                required_facts=(
                    "当前用户身份尚未通过服务端可信识别确认。",
                    "不能读取个人对话记录。",
                ),
                response_goal="自然说明暂时不能读取个人对话记录，并提示需要先确认身份。",
                constraints=(
                    "不要透露任何历史对话内容。",
                    "不要假装已经认识用户。",
                ),
            )

        if dated_recall and recall_intent.day_offset is not None:
            return _dated_conversation_recall_reply(
                dated_recall,
                target_role=recall_intent.target_role or "user",
            )

        target_role = recall_intent.target_role or "user"
        utterances: list[str] = []
        for item in reversed(context):
            if str(item.get("role") or "") != target_role:
                continue
            content = str(item.get("content") or "").strip()
            if not content or is_conversation_recall_query(content):
                continue
            topic = conversation_topic(content)
            if not topic:
                continue
            utterances.append(topic)
            if len(utterances) >= 2:
                break

        if not utterances:
            if target_role == "assistant":
                text = "我暂时没有找到刚才可以复述的回答。"
            else:
                text = "我记得你，不过暂时没有找到可以回顾的历史对话。"
            return PersonContextReply(
                intent=CONVERSATION_RECALL_INTENT,
                text="没有找到可回忆的历史对话。",
                identity_verified=True,
                required_facts=(text,),
                response_goal="自然告知没有找到可回忆的历史对话。",
                constraints=("不要编造历史内容。",),
            )

        if target_role == "assistant":
            answer = f"刚才我回答过的内容主题：{utterances[0]}。"
            response_goal = "回答用户刚才你说了什么，用第一人称概括我的回答大意。"
        elif len(utterances) == 1:
            answer = f"刚才我们聊到的主题：{utterances[0]}。"
            response_goal = "回答用户刚才或上次聊了什么，结合问题自然概括对话主题。"
        else:
            answer = (
                f"刚才我们聊到的主题：{utterances[0]}；"
                f"再之前的主题：{utterances[1]}。"
            )
            response_goal = "回答用户刚才或上次聊了什么，按重要性自然概括最近的对话主题。"
        return PersonContextReply(
            intent=CONVERSATION_RECALL_INTENT,
            text=answer,
            identity_verified=True,
            source_messages=len(utterances),
            required_facts=(answer,),
            response_goal=response_goal,
            constraints=(
                "先理解用户问的是“我说过什么”还是“我们聊过什么”，再组织回答。",
                "不要逐字背诵对话日志，不要输出“你说...我回...”格式。",
                "不要直接照抄事实材料，不要固定以“记得”开头。",
            ),
        )


def _clip_utterance(text: str, *, max_chars: int = 64) -> str:
    text = " ".join((text or "").split())
    if len(text) <= max_chars:
        return text
    return text[: max(1, max_chars - 1)].rstrip() + "…"


def conversation_recall_day_offset(text: str) -> int | None:
    """Return a relative day offset for date-scoped conversation recall."""

    intent = parse_conversation_recall_intent(text)
    if not intent.matched or intent.needs_clarification:
        return None
    return intent.day_offset


def conversation_recall_day_label(offset: int, target_date: str) -> str:
    if offset == 0:
        return "今天"
    if offset == -1:
        return "昨天"
    if offset == -2:
        return "前天"
    return target_date or "那天"


def _conversation_recall_clarification(
    recall_intent: ConversationRecallIntent,
) -> str:
    label = _conversation_recall_label_from_intent(recall_intent)
    if recall_intent.target_role == "assistant":
        return f"你是想让我复述{label}我说过的话吗？"
    return f"你是想让我回忆{label}我们聊过什么吗？"


def _conversation_recall_label_from_intent(
    recall_intent: ConversationRecallIntent,
) -> str:
    if recall_intent.day_offset == 0:
        return "今天"
    if recall_intent.day_offset == -1:
        return "昨天"
    if recall_intent.day_offset == -2:
        return "前天"
    if recall_intent.time_scope == "just_now":
        return "刚才"
    if recall_intent.time_scope == "previous":
        return "之前"
    return ""


def _dated_conversation_recall_reply(
    dated_recall: Mapping[str, Any],
    *,
    target_role: str,
) -> PersonContextReply:
    label = str(dated_recall.get("target_label") or "").strip()
    target_date = str(dated_recall.get("target_date") or "").strip()
    label = label or target_date or "那天"
    summary = str(dated_recall.get("summary") or "").strip()
    if summary:
        topic = recall_summary_topic(summary, max_chars=140)
        if not topic:
            topic = _clip_utterance(summary, max_chars=140)
        prefix = f"我{label}主要回答过" if target_role == "assistant" else f"{label}我们主要聊到"
        goal = (
            f"回答用户{label}你说过什么，用第一人称概括我的回答大意。"
            if target_role == "assistant"
            else f"回答用户{label}我们聊了什么，按用户问题自然概括主题。"
        )
        fact = f"{prefix}：{topic}。"
        return PersonContextReply(
            intent=CONVERSATION_RECALL_INTENT,
            text=fact,
            identity_verified=True,
            source_messages=int(dated_recall.get("source_turn_count") or 1),
            required_facts=(fact,),
            response_goal=goal,
            constraints=(
                "不要输出“用户聊了”“该用户询问了”等第三人称日志腔。",
                "不要逐字背诵对话日志，不要输出“你说...我回...”格式。",
                "不要直接照抄事实材料，不要固定以“记得”开头。",
            ),
        )

    turns = dated_recall.get("turns") or ()
    snippets: list[str] = []
    for item in reversed(list(turns)):
        if not isinstance(item, Mapping):
            continue
        text_key = "assistant_text" if target_role == "assistant" else "user_text"
        user_text = str(item.get(text_key) or "").strip()
        if not user_text or is_conversation_recall_query(user_text):
            continue
        snippet = conversation_topic(user_text, max_chars=42)
        if not snippet:
            continue
        snippets.append(snippet)
        if len(snippets) >= 3:
            break

    if not snippets:
        return PersonContextReply(
            intent=CONVERSATION_RECALL_INTENT,
            text=f"没有找到{label}的历史对话记录。",
            identity_verified=True,
            source_messages=0,
            required_facts=(
                f"已确认当前用户身份，但暂时没有找到{label}的历史对话记录。",
            ),
            response_goal="自然告知没有找到对应日期的历史对话记录。",
            constraints=("不要编造历史内容。",),
        )

    snippets.reverse()
    prefix = f"我{label}主要回答过" if target_role == "assistant" else f"{label}我们主要聊到"
    goal = (
        f"回答用户{label}你说过什么，用第一人称概括我的回答大意。"
        if target_role == "assistant"
        else f"回答用户{label}我们聊了什么，按用户问题自然概括主题。"
    )
    fact = f"{prefix}：" + "；".join(snippets) + "。"
    return PersonContextReply(
        intent=CONVERSATION_RECALL_INTENT,
        text=fact,
        identity_verified=True,
        source_messages=len(snippets),
        required_facts=(fact,),
        response_goal=goal,
        constraints=(
            "不要逐字背诵对话日志，不要输出“你说...我回...”格式。",
            "不要直接照抄事实材料，不要固定以“记得”开头。",
        ),
    )

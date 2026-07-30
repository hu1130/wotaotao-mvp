"""Shared intent routing for deciding whether dialog should use knowledge.

This module is deliberately configuration-independent so both the local
realtime client and the server-side Omni pipeline use the same routing rules.
Callers inject their own retrieval thresholds and knowledge service.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from typing import Any, Callable


logger = logging.getLogger(__name__)

ROUTE_CHAT = "chat"
ROUTE_KNOWLEDGE = "knowledge"

INTENT_CHAT = "chat"
INTENT_PERSONAL = "personal"
INTENT_COMPANY = "company"

DEFAULT_INTENT_EMBEDDING_MIN_SCORE = 0.72
DEFAULT_COMPANY_KNOWLEDGE_MIN_SCORE = 0.35

CHAT_PATTERNS = (
    r"^(你好|您好|哈喽|hello|hi|嗨)[呀啊吗嘛\W]*$",
    r"^(早上好|中午好|晚上好|再见|拜拜)[\W]*$",
    r"^(谢谢|多谢|辛苦了|没事|好的|可以|可以了|行|嗯|哦|好|ok)[\W]*$",
    r"^回复[\s:：]*(ok|好的|可以|行)[\W]*$",
    r"^(不想了解|不想知道|不用了|不需要|先不用|暂时不用|算了|没兴趣)[呀啊吗嘛呢\W]*$",
    r"(你叫什么|你是谁|你是哪个|你是哪位|你多大|你在干嘛|陪我聊|讲个笑话|唱首歌)",
    r"(神经病|有病吧|烦不烦|别说了|闭嘴|滚)",
)

ASSISTANT_IDENTITY_PATTERNS = (
    r"你(?:是(?:谁|哪个|哪位)|叫什么(?:名字)?|叫啥|叫什[么麼])",
    r"你(?:的)?名字(?:是|叫)?什[么麼]",
    r"你(?:这个|这位|这)?(?:数字人|前台|助手)?(?:叫啥|叫什么(?:名字)?|名字(?:是|叫)?什[么麼])",
)

SELF_IDENTITY_PATTERNS = (
    r"(?:你)?(?:还)?(?:知道|记得|认识|认得)(?:我是谁|我叫什么(?:名字)?|我)",
    r"(?:请问)?我(?:是谁|叫什么(?:名字)?)",
)

CONVERSATION_RECALL_TIME_SLOTS: tuple[tuple[str, tuple[str, ...], int | None], ...] = (
    ("day_before_yesterday", ("前天", "前日"), -2),
    ("yesterday", ("昨天", "昨日", "昨儿", "昨晚", "卓天"), -1),
    ("today", ("今天", "今日"), 0),
    ("just_now", ("刚才", "刚刚", "刚", "刚才的"), None),
    ("previous", ("上次", "之前", "以前", "前面", "上回"), None),
)

CONVERSATION_RECALL_MEMORY_SLOTS = (
    "记得",
    "记不记得",
    "还记得",
    "知道",
    "想起",
    "回忆",
    "复盘",
    "总结",
)

CONVERSATION_EVENT_SLOTS = (
    "聊",
    "聊过",
    "说",
    "说过",
    "问",
    "问过",
    "提",
    "提过",
    "讲",
    "讲过",
    "回答",
    "答",
    "交流",
)

CONVERSATION_RECALL_QUESTION_SLOTS = (
    "什么",
    "什麼",
    "啥",
    "哪些",
    "哪几",
    "多少",
    "来着",
    "?",
    "？",
)

CONVERSATION_RECALL_FINAL_QUESTION_PARTICLES = ("吗", "嘛", "呢")

CONVERSATION_RECALL_REQUEST_SLOTS = (
    "回忆",
    "复盘",
    "总结",
    "说说",
    "讲讲",
    "告诉我",
    "帮我",
    "帮忙",
)

CONVERSATION_HEARING_CLARIFICATION_SLOTS = (
    "听不清",
    "没听清",
    "没有听清",
    "听不见",
    "听不到",
    "听不懂",
    "没听懂",
    "没有听懂",
    "没听明白",
    "没有听明白",
)

PERSONAL_CONTEXT_PATTERNS = (
    r"(?:你)?(?:还)?(?:知道|记得|记住)(?:了)?(?:我|我的|给我|帮我|关于我).*(?:什么|啥|哪些|吗)?",
    r"(?:我)?(?:让|叫|要|请)(?:你|你帮我)?(?:记住|记得).*(?:什么|啥|哪些|吗)?",
    r"(?:我|我的).*(?:喜欢|偏好|习惯|性格|生日|名字|称呼|目标|计划|爱好|口味|忌口|常喝|常用|经常).*(?:什么|啥|哪些|吗)?",
    r"(?:我|我的).*(?:个人|私人|自己的).*(?:资料|信息|记忆|偏好|知识|总结)",
    r"(?:关于我|跟我有关|和我有关).*(?:记住|记得|知道|总结|信息|资料|内容)",
    r"(?:你)?(?:还)?(?:知道|记得).*(?:我喜欢|我的偏好|我的习惯|我的目标|我的计划)",
)

KNOWLEDGE_KEYWORDS = {
    "AI口播",
    "AI视频生成",
    "AI营销",
    "AI人事",
    "一键换衣",
    "公司",
    "企业",
    "产品",
    "业务",
    "项目",
    "方案",
    "报价",
    "价格",
    "费用",
    "流程",
    "制度",
    "规定",
    "资料",
    "文档",
    "介绍",
    "面试",
    "招聘",
    "岗位",
    "入职",
    "签到",
    "签退",
    "考勤",
    "客户",
    "合作",
    "数字人",
    "智能客服",
    "智能前台",
    "前台系统",
    "营销话术",
    "营销系统",
    "竞品分析",
    "口播",
    "视频生成",
    "人事系统",
    "超级员工",
    "外贸",
    "外贸版",
    "客户问题",
    "产品文档",
    "产品介绍",
    "产品分析",
    "公司介绍",
    "面试流程",
    "深度觉醒",
}

CHAT_EXAMPLES = (
    "你好，早上好",
    "谢谢你，辛苦了",
    "没事了，不用了",
    "陪我聊聊天",
    "讲个笑话",
    "你叫什么名字",
    "今天心情不错",
    "我有点累，想聊一会儿",
    "你是哪个",
    "别说了，烦不烦",
)

PERSONAL_EXAMPLES = (
    "你记住了我什么",
    "我喜欢喝什么",
    "我的偏好是什么",
    "你知道我的习惯吗",
    "关于我你记得哪些信息",
    "我让你记住了什么",
    "我是谁",
    "我们刚才聊了什么",
)

COMPANY_EXAMPLES = (
    "公司业务流程是什么",
    "介绍一下你们公司的产品",
    "公司制度有哪些",
    "考勤规则是什么",
    "客户合作方案怎么做",
    "项目报价是多少",
    "岗位招聘要求是什么",
    "企业资料在哪里",
    "AI智能客服产品文档",
    "AI智能客服竞品分析",
    "AI智能客服营销话术",
    "数字人智能前台产品分析",
    "数字人智能前台系统产品介绍",
    "AI口播产品文档",
    "AI口播竞品分析",
    "AI口播营销话术",
    "AI视频生成产品文档",
    "AI视频生成竞品分析",
    "AI视频生成营销话术",
    "AI一键换衣产品文档",
    "一键换衣客户可能会问的问题",
    "AI营销系统产品介绍",
    "AI营销系统客户问题",
    "AI人事系统产品介绍",
    "AI人事系统客户可能会问的问题",
    "AI超级员工系统外贸版产品介绍",
    "AI超级员工系统客户可能会问的问题",
    "深度觉醒产品信息",
    "深度觉醒公司介绍",
    "公司面试流程",
    "公司吃饭和用餐安排",
)

INTENT_EXAMPLES: tuple[tuple[str, str], ...] = tuple(
    (INTENT_CHAT, text) for text in CHAT_EXAMPLES
) + tuple((INTENT_PERSONAL, text) for text in PERSONAL_EXAMPLES) + tuple(
    (INTENT_COMPANY, text) for text in COMPANY_EXAMPLES
)

_INTENT_EXAMPLE_VECTOR_CACHE: dict[tuple[Any, ...], list[tuple[str, str, list[float]]]] = {}

QUESTION_HINTS = {
    "是什么",
    "有哪些",
    "怎么",
    "如何",
    "为什么",
    "多少",
    "多久",
    "哪里",
    "谁负责",
    "能不能介绍",
    "讲一下",
    "说一下",
}


@dataclass(frozen=True)
class DialogIntentRoute:
    route: str
    reason: str
    confidence: float = 0.0
    results: list[Any] = field(default_factory=list)
    intent: str = ""
    knowledge_probed: bool = False
    knowledge_min_score: float = 0.0

    @property
    def use_knowledge(self) -> bool:
        return self.route == ROUTE_KNOWLEDGE


class DialogIntentRouter:
    """Deterministic gate before optional knowledge retrieval."""

    def __init__(
        self,
        knowledge_service_factory: Callable[[], Any] | None = None,
        *,
        min_score: float = 0.12,
        probe_knowledge: bool = True,
        probe_top_k: int = 1,
        intent_embedding_factory: Callable[[], Any] | None = None,
        intent_embedding_enabled: bool = True,
        intent_embedding_min_score: float = DEFAULT_INTENT_EMBEDDING_MIN_SCORE,
        default_company_min_score: float = DEFAULT_COMPANY_KNOWLEDGE_MIN_SCORE,
    ) -> None:
        self.knowledge_service_factory = (
            knowledge_service_factory or default_knowledge_service_factory
        )
        self.min_score = min_score
        self.probe_knowledge = probe_knowledge
        self.probe_top_k = max(1, probe_top_k)
        self.intent_embedding_factory = intent_embedding_factory
        self.intent_embedding_enabled = intent_embedding_enabled
        self.intent_embedding_min_score = intent_embedding_min_score
        self.default_company_min_score = default_company_min_score

    def route(self, text: str) -> DialogIntentRoute:
        query = normalize_query(text)
        if not query:
            return DialogIntentRoute(ROUTE_CHAT, "empty_query", intent=INTENT_CHAT)

        has_question_hint = self._has_question_hint(query)
        if is_likely_incomplete_query(query, has_question_hint=has_question_hint):
            return DialogIntentRoute(
                ROUTE_CHAT,
                "incomplete_query",
                intent=INTENT_CHAT,
            )

        intent = classify_person_company_intent(
            query,
            embedding_factory=self._intent_embedding_provider,
            embedding_enabled=self.intent_embedding_enabled,
            embedding_min_score=self.intent_embedding_min_score,
        )

        if intent.intent == INTENT_CHAT:
            return DialogIntentRoute(
                ROUTE_CHAT,
                intent.reason,
                confidence=intent.confidence,
                intent=intent.intent,
            )

        if intent.intent == INTENT_PERSONAL:
            return DialogIntentRoute(
                ROUTE_CHAT,
                intent.reason,
                confidence=intent.confidence,
                intent=intent.intent,
            )

        results: list[Any] = []
        top_score = 0.0
        probe_error = ""
        probe_min_score = self._knowledge_probe_min_score(intent)

        if self.probe_knowledge:
            try:
                results = self.knowledge_service_factory().search(
                    query,
                    top_k=self.probe_top_k,
                    min_score=probe_min_score,
                )
                top_score = results[0].score if results else 0.0
            except Exception as exc:
                probe_error = str(exc)
                logger.warning("意图路由知识库 probe 失败: query=%s error=%s", query, exc)

        if results:
            return DialogIntentRoute(
                ROUTE_KNOWLEDGE,
                f"{intent.reason}_knowledge_probe_hit",
                confidence=top_score,
                results=results,
                intent=INTENT_COMPANY,
                knowledge_probed=True,
                knowledge_min_score=probe_min_score,
            )

        reason = intent.reason
        if self.probe_knowledge:
            reason = f"{reason}_knowledge_probe_miss"
        if probe_error:
            reason = f"{reason}: {probe_error[:120]}"
        return DialogIntentRoute(
            ROUTE_KNOWLEDGE,
            reason,
            confidence=intent.confidence,
            intent=INTENT_COMPANY,
            knowledge_probed=bool(self.probe_knowledge),
            knowledge_min_score=probe_min_score if self.probe_knowledge else 0.0,
        )

    def _is_obvious_chat(self, query: str) -> bool:
        return any(re.search(pattern, query, re.IGNORECASE) for pattern in CHAT_PATTERNS)

    def _keyword_score(self, query: str) -> int:
        return sum(1 for keyword in KNOWLEDGE_KEYWORDS if keyword in query)

    def _has_question_hint(self, query: str) -> bool:
        return "?" in query or "？" in query or any(
            hint in query for hint in QUESTION_HINTS
        )

    def _intent_embedding_provider(self) -> Any:
        if self.intent_embedding_factory is not None:
            return self.intent_embedding_factory()
        service = self.knowledge_service_factory()
        return getattr(service, "embedding_client", None)

    def _knowledge_probe_min_score(self, intent: "DialogQueryIntent") -> float:
        if intent.reason in {
            "default_company_intent",
            "intent_embedding_error_default_company",
        }:
            return max(self.min_score, self.default_company_min_score)
        return self.min_score


@dataclass(frozen=True)
class DialogQueryIntent:
    intent: str
    reason: str
    confidence: float = 0.0


@dataclass(frozen=True)
class ConversationRecallIntent:
    """Structured result for personal conversation recall routing."""

    matched: bool
    needs_clarification: bool = False
    confidence: float = 0.0
    time_scope: str = ""
    day_offset: int | None = None
    target_role: str = ""
    reason: str = ""


def classify_person_company_intent(
    text: str,
    *,
    embedding_factory: Callable[[], Any] | None = None,
    embedding_enabled: bool = True,
    embedding_min_score: float = DEFAULT_INTENT_EMBEDDING_MIN_SCORE,
) -> DialogQueryIntent:
    """Classify a query as chat, personal memory, or company knowledge."""

    compact = compact_query(text)
    if not compact:
        return DialogQueryIntent(INTENT_CHAT, "empty_query", 0.0)

    keyword_intent = classify_keyword_intent(compact)
    if keyword_intent is not None:
        return keyword_intent

    if embedding_enabled and embedding_factory is not None:
        embedding_intent = classify_embedding_intent(
            compact,
            embedding_factory=embedding_factory,
            min_score=embedding_min_score,
        )
        if embedding_intent is not None:
            return embedding_intent

    return DialogQueryIntent(INTENT_COMPANY, "default_company_intent", 0.0)


def classify_keyword_intent(text: str) -> DialogQueryIntent | None:
    compact = compact_query(text)
    if not compact:
        return DialogQueryIntent(INTENT_CHAT, "empty_query", 0.0)
    if is_assistant_identity_query(compact):
        return DialogQueryIntent(INTENT_CHAT, "keyword_assistant_identity", 0.94)
    recall_intent = parse_conversation_recall_intent(compact)
    if recall_intent.matched or recall_intent.needs_clarification:
        return DialogQueryIntent(INTENT_PERSONAL, "keyword_personal_context", 0.92)
    if _has_company_scope(compact):
        return DialogQueryIntent(INTENT_COMPANY, "keyword_company_scope", 0.92)
    if (
        is_self_identity_query(compact)
        or is_personal_context_query(compact)
    ):
        return DialogQueryIntent(INTENT_PERSONAL, "keyword_personal_context", 0.92)
    if any(re.search(pattern, compact, re.IGNORECASE) for pattern in CHAT_PATTERNS):
        return DialogQueryIntent(INTENT_CHAT, "keyword_obvious_chat", 0.9)
    return None


def classify_embedding_intent(
    text: str,
    *,
    embedding_factory: Callable[[], Any],
    min_score: float = DEFAULT_INTENT_EMBEDDING_MIN_SCORE,
) -> DialogQueryIntent | None:
    compact = compact_query(text)
    if not compact:
        return DialogQueryIntent(INTENT_CHAT, "empty_query", 0.0)
    try:
        provider = embedding_factory()
        if provider is None:
            return None
        query_vector, example_vectors = _load_intent_embeddings(provider, compact)
    except Exception as exc:
        logger.warning("意图 embedding 分类失败: query=%s error=%s", text, exc)
        return DialogQueryIntent(INTENT_COMPANY, "intent_embedding_error_default_company", 0.0)

    best_intent = ""
    best_example = ""
    best_score = -1.0
    for intent, example, vector in example_vectors:
        score = cosine_similarity(query_vector, vector)
        if score > best_score:
            best_intent = intent
            best_example = example
            best_score = score
    if best_score < min_score:
        return None
    return DialogQueryIntent(
        best_intent,
        f"embedding_{best_intent}_intent:{best_example}",
        best_score,
    )


def _load_intent_embeddings(
    provider: Any,
    query: str,
) -> tuple[list[float], list[tuple[str, str, list[float]]]]:
    cache_key = _intent_embedding_cache_key(provider)
    examples = _INTENT_EXAMPLE_VECTOR_CACHE.get(cache_key)
    if examples is None:
        texts = [example for _, example in INTENT_EXAMPLES]
        vectors = provider.embed_texts(texts)
        if len(vectors) != len(INTENT_EXAMPLES):
            raise RuntimeError(
                f"intent embedding returned {len(vectors)} examples, expected {len(INTENT_EXAMPLES)}"
            )
        examples = [
            (intent, example, vector)
            for (intent, example), vector in zip(INTENT_EXAMPLES, vectors)
        ]
        _INTENT_EXAMPLE_VECTOR_CACHE[cache_key] = examples
    if hasattr(provider, "embed_query"):
        query_vector = provider.embed_query(query)
    else:
        vectors = provider.embed_texts([query])
        if not vectors:
            raise RuntimeError("intent embedding returned no query vector")
        query_vector = vectors[0]
    return query_vector, examples


def _intent_embedding_cache_key(provider: Any) -> tuple[Any, ...]:
    return (
        provider.__class__.__module__,
        provider.__class__.__qualname__,
        getattr(provider, "api_base", ""),
        getattr(provider, "model", ""),
        getattr(provider, "dimension", ""),
    )


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm <= 0.0 or right_norm <= 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


def is_self_identity_query(text: str) -> bool:
    """Return whether the user is directly asking about their own identity."""

    compact = compact_query(text)
    return bool(compact) and any(
        re.fullmatch(pattern, compact, re.IGNORECASE)
        for pattern in SELF_IDENTITY_PATTERNS
    )


def is_assistant_identity_query(text: str) -> bool:
    """Return whether the user asks who the assistant is or what it is called."""

    compact = compact_query(text)
    return bool(compact) and any(
        re.search(pattern, compact, re.IGNORECASE)
        for pattern in ASSISTANT_IDENTITY_PATTERNS
    )


def is_conversation_recall_query(text: str) -> bool:
    """Return whether the user asks to recall an earlier conversation."""

    intent = parse_conversation_recall_intent(text)
    return intent.matched and not intent.needs_clarification


def parse_conversation_recall_intent(text: str) -> ConversationRecallIntent:
    """Parse whether text is asking to recall prior conversation history.

    The parser uses independent slots instead of whole-sentence regexes so ASR
    fillers and word-order variants can still be routed deterministically.
    """

    raw = _slot_query(text)
    if not raw:
        return ConversationRecallIntent(False, reason="empty_query")
    if _contains_any(raw, CONVERSATION_HEARING_CLARIFICATION_SLOTS):
        return ConversationRecallIntent(False, reason="hearing_clarification")
    time_scope, day_offset = _conversation_recall_time_slot(raw)
    has_time = bool(time_scope)
    has_memory_slot = _contains_any(raw, CONVERSATION_RECALL_MEMORY_SLOTS)
    if is_assistant_identity_query(raw) and not (has_time or has_memory_slot):
        return ConversationRecallIntent(False, reason="assistant_identity_query")

    has_event_slot = _contains_any(raw, CONVERSATION_EVENT_SLOTS)
    has_question_slot = _has_conversation_recall_question_slot(raw)
    has_request_slot = _contains_any(raw, CONVERSATION_RECALL_REQUEST_SLOTS)
    has_person_scope = bool(re.search(r"(?:我|我们|咱们)", raw))
    assistant_target = _is_assistant_recall_target(raw)
    user_target = _is_user_recall_target(raw)

    if not has_event_slot:
        return ConversationRecallIntent(False, reason="missing_conversation_event")

    if _has_company_scope(raw) and not (
        has_person_scope or has_memory_slot or assistant_target or user_target
    ):
        return ConversationRecallIntent(
            False,
            reason="company_scope_without_personal_recall",
        )

    asks_for_recall = has_question_slot or has_request_slot
    recall_scope = (
        has_time
        or has_memory_slot
        or has_person_scope
        or assistant_target
        or user_target
    )
    if asks_for_recall and recall_scope:
        return ConversationRecallIntent(
            True,
            confidence=_conversation_recall_confidence(
                has_time=has_time,
                has_memory_slot=has_memory_slot,
                has_question_slot=has_question_slot,
                has_request_slot=has_request_slot,
                has_person_scope=has_person_scope,
                assistant_target=assistant_target,
            ),
            time_scope=time_scope,
            day_offset=day_offset,
            target_role="assistant" if assistant_target and not user_target else "user",
            reason="slot_conversation_recall",
        )

    if has_time and (has_person_scope or has_memory_slot) and not _has_company_scope(raw):
        return ConversationRecallIntent(
            False,
            needs_clarification=True,
            confidence=0.58,
            time_scope=time_scope,
            day_offset=day_offset,
            target_role="assistant" if assistant_target and not user_target else "user",
            reason="ambiguous_conversation_recall_statement",
        )

    return ConversationRecallIntent(False, reason="insufficient_recall_slots")


def is_personal_context_query(text: str) -> bool:
    """Return whether the user is asking about their own memory or preferences."""

    compact = compact_query(text)
    if not compact:
        return False
    if _has_company_scope(compact):
        return False
    return any(
        re.fullmatch(pattern, compact, re.IGNORECASE)
        for pattern in PERSONAL_CONTEXT_PATTERNS
    )


def conversation_recall_target_role(text: str) -> str:
    """Return which side of the prior conversation the user asks to recall."""

    return parse_conversation_recall_intent(text).target_role


def _slot_query(text: str) -> str:
    compact = re.sub(r"\s+", "", normalize_query(text))
    return re.sub(r"[，。！,.!;；:：、]+$", "", compact)


def _contains_any(text: str, tokens: tuple[str, ...]) -> bool:
    return any(token in text for token in tokens)


def _has_conversation_recall_question_slot(text: str) -> bool:
    if _contains_any(text, CONVERSATION_RECALL_QUESTION_SLOTS):
        return True
    return text.endswith(CONVERSATION_RECALL_FINAL_QUESTION_PARTICLES)


def _conversation_recall_time_slot(text: str) -> tuple[str, int | None]:
    for scope, tokens, offset in CONVERSATION_RECALL_TIME_SLOTS:
        if any(token in text for token in tokens):
            return scope, offset
    return "", None


def _is_assistant_recall_target(text: str) -> bool:
    return bool(
        re.search(r"你.{0,8}(?:刚才|刚刚|上次|之前|以前)?(?:跟我)?(?:说|讲|回答|答)", text)
        or re.search(r"(?:刚才|刚刚|上次|之前|以前)?你(?:跟我)?(?:说|讲|回答|答)", text)
    )


def _is_user_recall_target(text: str) -> bool:
    return bool(
        re.search(r"(?:我|我们|咱们).{0,12}(?:跟你)?(?:说|问|聊|提|讲)", text)
        or re.search(r"(?:说|问|聊|提|讲).{0,12}(?:我|我们|咱们)", text)
    )


def _conversation_recall_confidence(
    *,
    has_time: bool,
    has_memory_slot: bool,
    has_question_slot: bool,
    has_request_slot: bool,
    has_person_scope: bool,
    assistant_target: bool,
) -> float:
    score = 0.55
    if has_time:
        score += 0.12
    if has_memory_slot:
        score += 0.1
    if has_question_slot:
        score += 0.11
    if has_request_slot:
        score += 0.08
    if has_person_scope or assistant_target:
        score += 0.08
    return min(score, 0.96)


def compact_query(text: str) -> str:
    compact = re.sub(r"\s+", "", normalize_query(text))
    compact = re.sub(r"[，。！？,.!?;；:：、]+$", "", compact)
    compact = re.sub(r"[吗嘛呢呀啊]+$", "", compact)
    compact = re.sub(r"(?<!什)么$", "", compact)
    return compact


def normalize_query(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def is_likely_incomplete_query(
    text: str,
    *,
    has_question_hint: bool = False,
) -> bool:
    """Reject trailing ASR fragments before they probe tenant knowledge."""

    query = normalize_query(text)
    if not query or has_question_hint or "?" in query or "？" in query:
        return False
    compact = re.sub(r"[，。！,.!;；:：、\s]+$", "", query)
    return bool(
        compact
        and re.search(r"(?:的|是|和|与|或|以及|关于|因为|但是|然后)$", compact)
    )


def _has_company_scope(text: str) -> bool:
    return any(
        keyword in text
        for keyword in (
            "公司",
            "企业",
            "产品",
            "业务",
            "项目",
            "客户",
            "岗位",
            "招聘",
            "入职",
            "考勤",
            "制度",
            "数字人",
            "智能客服",
            "智能前台",
            "前台系统",
            "AI口播",
            "口播",
            "AI视频生成",
            "视频生成",
            "一键换衣",
            "AI营销",
            "营销话术",
            "营销系统",
            "竞品分析",
            "AI人事",
            "人事系统",
            "超级员工",
            "外贸版",
            "客户问题",
            "产品文档",
            "产品介绍",
            "产品分析",
            "公司介绍",
            "面试流程",
            "深度觉醒",
        )
    )


def default_knowledge_service_factory() -> Any:
    from core.knowledge.service import KnowledgeService

    return KnowledgeService()

"""Text chat backend for the avatar voice demo."""

from __future__ import annotations

import logging
import json
import re
import threading
import time
from dataclasses import dataclass
from collections.abc import Iterator

import requests
from requests.adapters import HTTPAdapter

from config import (
    DIALOG_CHAT_API_BASE,
    DIALOG_CHAT_API_KEY,
    DIALOG_CHAT_CONNECT_TIMEOUT_SECONDS,
    DIALOG_CHAT_DEFAULT_COMPANY_RAG_MIN_SCORE,
    DIALOG_CHAT_INTENT_ROUTER_ENABLED,
    DIALOG_CHAT_INTENT_ROUTER_MIN_SCORE,
    DIALOG_CHAT_INTENT_ROUTER_PROBE_KNOWLEDGE,
    DIALOG_CHAT_INTENT_ROUTER_PROBE_TOP_K,
    DIALOG_CHAT_HTTP_POOL_CONNECTIONS,
    DIALOG_CHAT_HTTP_POOL_MAXSIZE,
    DIALOG_CHAT_ENABLE_THINKING,
    DIALOG_CHAT_INTENT_EMBEDDING_ENABLED,
    DIALOG_CHAT_INTENT_EMBEDDING_MIN_SCORE,
    DIALOG_CHAT_MAX_RETRIES,
    DIALOG_CHAT_MAX_TOKENS,
    DIALOG_CHAT_MODEL,
    DIALOG_CHAT_RAG_ENABLED,
    DIALOG_CHAT_RAG_FALLBACK_TO_LLM,
    DIALOG_CHAT_RAG_MAX_CONTEXT_CHARS,
    DIALOG_CHAT_RAG_MIN_SCORE,
    DIALOG_CHAT_RAG_TOP_K,
    DIALOG_CHAT_SYSTEM_PROMPT,
    DIALOG_CHAT_TEMPERATURE,
    DIALOG_CHAT_TIMEOUT_SECONDS,
    DIALOG_CHAT_WARMUP_TEXT,
    DIALOG_SCENE_REPLY_MAX_TOKENS,
    DIALOG_SCENE_REPLY_TEMPERATURE,
    VOICE_ASSISTANT_WAKE_REPLY,
)
from core.dialog_wake_name import parse_wake_name
from core.dialog_intent_router import DialogIntentRouter, is_assistant_identity_query
from core.knowledge.models import SearchResult
from core.knowledge.service import KnowledgeService, get_knowledge_service
from core.tenant import DEFAULT_TENANT_ID, normalize_tenant_id
from core.tenant_avatar import get_tenant_avatar_persona_service

logger = logging.getLogger(__name__)


class DialogChatError(RuntimeError):
    pass


@dataclass(frozen=True)
class LocalQuickReplyScene:
    scene: str
    canonical_text: str
    response_goal: str
    constraints: tuple[str, ...] = ()


class DialogChatService:
    def __init__(self):
        self.api_base = DIALOG_CHAT_API_BASE
        self.api_key = DIALOG_CHAT_API_KEY
        self.model = DIALOG_CHAT_MODEL
        self.max_tokens = max(0, DIALOG_CHAT_MAX_TOKENS)
        self.enable_thinking = DIALOG_CHAT_ENABLE_THINKING
        self.rag_enabled = DIALOG_CHAT_RAG_ENABLED
        self.intent_router_enabled = DIALOG_CHAT_INTENT_ROUTER_ENABLED
        self._session_lock = threading.RLock()
        self.session = self._build_session()

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        adapter = HTTPAdapter(
            pool_connections=DIALOG_CHAT_HTTP_POOL_CONNECTIONS,
            pool_maxsize=DIALOG_CHAT_HTTP_POOL_MAXSIZE,
            max_retries=0,
            pool_block=True,
        )
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        session.headers.update(
            {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
        )
        return session

    def _reset_session(self) -> None:
        with self._session_lock:
            old_session = self.session
            self.session = self._build_session()
        try:
            old_session.close()
        except Exception:
            pass

    @property
    def ready(self) -> bool:
        return bool(self.api_base and self.api_key and self.model)

    def reply(self, text: str, tenant_id: str = DEFAULT_TENANT_ID) -> dict:
        text = (text or "").strip()
        if not text:
            raise DialogChatError("text is required")
        if not self.ready:
            raise DialogChatError("dialog chat model is not configured")

        tenant_id = normalize_tenant_id(tenant_id)
        messages, sources = self._build_messages(text, tenant_id)
        payload = self._build_payload(messages)
        data = self._post_chat_completion(payload)

        answer = data["choices"][0]["message"]["content"].strip()
        return {
            "tenantId": tenant_id,
            "text": text,
            "answer": answer,
            "model": self.model,
            "sources": sources,
        }

    def stream_reply(
        self, text: str, tenant_id: str = DEFAULT_TENANT_ID
    ) -> Iterator[str]:
        text = (text or "").strip()
        if not text:
            raise DialogChatError("text is required")
        if not self.ready:
            raise DialogChatError("dialog chat model is not configured")

        tenant_id = normalize_tenant_id(tenant_id)
        persona = get_tenant_avatar_persona_service().resolve(tenant_id)
        quick_scene = classify_local_quick_reply_scene(text, persona=persona)
        if quick_scene:
            logger.info(
                "对话场景快速回复转模型生成: scene=%s query=%s canonical=%s",
                quick_scene.scene,
                extract_latest_user_query(text),
                quick_scene.canonical_text,
            )
            yield self.scene_reply(
                scene=quick_scene.scene,
                user_text=extract_latest_user_query(text),
                tenant_id=tenant_id,
                required_facts=[quick_scene.canonical_text],
                response_goal=quick_scene.response_goal,
                constraints=list(quick_scene.constraints),
            )
            return

        payload = self._build_payload(
            self._build_messages(text, tenant_id)[0],
            stream=True,
        )
        yield from self._stream_chat_completion(payload)

    def warmup(self) -> bool:
        if not self.ready:
            logger.warning("对话模型预热跳过: DIALOG_CHAT_* 未配置完整")
            return False
        started_at = time.perf_counter()
        try:
            self.reply(DIALOG_CHAT_WARMUP_TEXT)
        except Exception as exc:
            logger.warning("对话模型预热失败: %s", exc)
            return False
        logger.info("对话模型预热完成: %.0fms", (time.perf_counter() - started_at) * 1000)
        return True

    def scene_reply(
        self,
        *,
        scene: str,
        user_text: str = "",
        tenant_id: str = DEFAULT_TENANT_ID,
        context: list[dict] | None = None,
        user_info: dict | None = None,
        required_facts: list[str] | None = None,
        response_goal: str = "",
        constraints: list[str] | None = None,
    ) -> str:
        if not self.ready:
            raise DialogChatError("dialog chat model is not configured")

        tenant_id = normalize_tenant_id(tenant_id)
        persona = get_tenant_avatar_persona_service().resolve(tenant_id)
        messages = self._scene_messages(
            scene=scene,
            user_text=user_text,
            system_prompt=persona.chat_system_prompt,
            context=context or [],
            user_info=user_info or {},
            required_facts=required_facts or [],
            response_goal=response_goal,
            constraints=constraints or [],
        )
        payload = self._build_payload(
            messages,
            temperature=DIALOG_SCENE_REPLY_TEMPERATURE,
            max_tokens=DIALOG_SCENE_REPLY_MAX_TOKENS,
        )
        started_at = time.perf_counter()
        data = self._post_chat_completion(payload)
        answer = data["choices"][0]["message"]["content"].strip()
        if not answer:
            raise DialogChatError(f"scene reply returned empty answer: {scene}")
        logger.info(
            "动态场景话术生成完成: tenant=%s scene=%s user_chars=%d facts=%d answer_chars=%d elapsed_ms=%.0f",
            tenant_id,
            scene,
            len(user_text or ""),
            len(required_facts or []),
            len(answer),
            (time.perf_counter() - started_at) * 1000,
        )
        return answer

    def _build_messages(
        self, text: str, tenant_id: str = DEFAULT_TENANT_ID
    ) -> tuple[list[dict[str, str]], list[dict]]:
        tenant_id = normalize_tenant_id(tenant_id)
        persona = get_tenant_avatar_persona_service().resolve(tenant_id)
        if not self.rag_enabled and not self.intent_router_enabled:
            return self._plain_messages(text, persona.chat_system_prompt), []

        route_text = extract_latest_user_query(text)
        if self.intent_router_enabled:
            route = DialogIntentRouter(
                knowledge_service_factory=lambda: get_knowledge_service(tenant_id),
                min_score=DIALOG_CHAT_INTENT_ROUTER_MIN_SCORE,
                probe_knowledge=DIALOG_CHAT_INTENT_ROUTER_PROBE_KNOWLEDGE,
                probe_top_k=DIALOG_CHAT_INTENT_ROUTER_PROBE_TOP_K,
                intent_embedding_enabled=DIALOG_CHAT_INTENT_EMBEDDING_ENABLED,
                intent_embedding_min_score=DIALOG_CHAT_INTENT_EMBEDDING_MIN_SCORE,
                default_company_min_score=DIALOG_CHAT_DEFAULT_COMPANY_RAG_MIN_SCORE,
            ).route(route_text)
            logger.info(
                "对话意图路由: route=%s intent=%s reason=%s confidence=%.3f probe_min=%.3f query=%s raw_chars=%d",
                route.route,
                route.intent,
                route.reason,
                route.confidence,
                route.knowledge_min_score,
                route_text,
                len(text),
            )
            if not route.use_knowledge:
                return self._plain_messages(text, persona.chat_system_prompt), []
            if route.knowledge_probed:
                results = list(route.results)
                if not results:
                    if not DIALOG_CHAT_RAG_FALLBACK_TO_LLM:
                        raise DialogChatError(
                            "knowledge base has no reliable answer for this question"
                        )
                    return [
                        {"role": "system", "content": persona.chat_system_prompt},
                        {
                            "role": "user",
                            "content": (
                                f"{text}\n\n"
                                "本次没有从公司知识库检索到可靠资料。"
                                "如果问题涉及公司制度、流程或内部资料，请明确说明没有找到依据；"
                                "如果只是普通寒暄或通用问题，可以自然简短回答。"
                            ),
                        },
                    ], []
                return self._rag_messages(text, results, persona.chat_system_prompt)

        try:
            results = get_knowledge_service(tenant_id).search(
                route_text,
                top_k=DIALOG_CHAT_RAG_TOP_K,
                min_score=DIALOG_CHAT_RAG_MIN_SCORE,
            )
        except Exception as exc:
            logger.warning("语音对话 RAG 检索失败: %s", exc)
            if not DIALOG_CHAT_RAG_FALLBACK_TO_LLM:
                raise DialogChatError(f"knowledge retrieval failed: {exc}") from exc
            results = []

        if not results:
            if not DIALOG_CHAT_RAG_FALLBACK_TO_LLM:
                raise DialogChatError("knowledge base has no reliable answer for this question")
            return [
                {"role": "system", "content": persona.chat_system_prompt},
                {
                    "role": "user",
                    "content": (
                        f"{text}\n\n"
                        "本次没有从公司知识库检索到可靠资料。"
                        "如果问题涉及公司制度、流程或内部资料，请明确说明没有找到依据；"
                        "如果只是普通寒暄或通用问题，可以自然简短回答。"
                    ),
                },
            ], []

        return self._rag_messages(text, results, persona.chat_system_prompt)

    def _rag_messages(
        self,
        text: str,
        results: list[SearchResult],
        system_prompt: str,
    ) -> tuple[list[dict[str, str]], list[dict]]:
        sources = [KnowledgeService._result_to_dict(item) for item in results]
        context = self._format_rag_context(results)
        return [
            {
                "role": "system",
                "content": (
                    f"{system_prompt}\n"
                    "你现在已接入公司本地知识库。回答公司制度、流程、人员说明、内部资料相关问题时，"
                    "必须优先依据给定资料；资料不足时要直接说没有找到可靠依据。"
                    "回答适合语音播报，不输出 Markdown，不要朗读文件路径。"
                ),
            },
            {
                "role": "user",
                "content": f"用户问题：{text}\n\n公司知识库资料：\n{context}",
            },
        ], sources

    def _plain_messages(self, text: str, system_prompt: str) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": system_prompt or DIALOG_CHAT_SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ]

    def _scene_messages(
        self,
        *,
        scene: str,
        user_text: str,
        system_prompt: str,
        context: list[dict],
        user_info: dict,
        required_facts: list[str],
        response_goal: str,
        constraints: list[str],
    ) -> list[dict[str, str]]:
        scene = (scene or "frontdesk_dialog").strip()[:80]
        base_constraints = [
            "你只负责把已确定的业务结果改写成自然口语，不要改变业务事实。",
            "必须保留给定事实中的姓名、动作结果、确认要求、错误状态和后续步骤。",
            "不要编造未提供的信息，不要承诺系统尚未执行的动作。",
            "回答适合数字人口播，中文为主，不输出 Markdown。",
            "短而自然，一般一到两句话；同类场景避免复用固定开头、固定句式和固定语气词。",
        ]
        lines = [
            f"业务场景：{scene}",
            f"表达目标：{response_goal or '自然回应当前用户'}",
            f"用户最新话语：{(user_text or '').strip()[:500] or '无'}",
        ]
        if user_info:
            lines.append("当前用户信息：")
            for key, value in user_info.items():
                value_text = str(value or "").strip()
                if value_text:
                    lines.append(f"- {key}: {value_text[:160]}")
        if context:
            lines.append("最近对话上下文：")
            for item in context[-6:]:
                role = "用户" if item.get("role") == "user" else "数字人"
                content = str(item.get("content") or "").strip()
                if content:
                    lines.append(f"- {role}: {content[:220]}")
        if required_facts:
            lines.append("必须表达或保留的业务事实：")
            for fact in required_facts:
                fact_text = str(fact or "").strip()
                if fact_text:
                    lines.append(f"- {fact_text[:260]}")
        merged_constraints = [*base_constraints, *constraints]
        lines.append("回答约束：")
        for constraint in merged_constraints:
            constraint_text = str(constraint or "").strip()
            if constraint_text:
                lines.append(f"- {constraint_text[:220]}")
        return [
            {"role": "system", "content": system_prompt or DIALOG_CHAT_SYSTEM_PROMPT},
            {"role": "user", "content": "\n".join(lines)},
        ]

    def _format_rag_context(self, results: list[SearchResult]) -> str:
        parts = []
        used = 0
        for index, result in enumerate(results, start=1):
            header = f"[{index}] {result.citation_label()}\n"
            content = result.content.strip()
            remaining = DIALOG_CHAT_RAG_MAX_CONTEXT_CHARS - used - len(header)
            if remaining <= 0:
                break
            if len(content) > remaining:
                content = content[:remaining]
            parts.append(f"{header}{content}")
            used += len(header) + len(content)
        return "\n\n".join(parts)

    def _build_payload(
        self,
        messages: list[dict[str, str]],
        *,
        stream: bool = False,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict:
        payload: dict[str, object] = {
            "model": self.model,
            "messages": messages,
            "temperature": DIALOG_CHAT_TEMPERATURE if temperature is None else temperature,
        }
        if stream:
            payload["stream"] = True
        token_limit = self.max_tokens if max_tokens is None else max_tokens
        if token_limit > 0:
            payload["max_tokens"] = token_limit
        if "dashscope.aliyuncs.com" in self.api_base and not self.enable_thinking:
            payload["enable_thinking"] = False
        return payload

    def _post_chat_completion(self, payload: dict) -> dict:
        last_error: Exception | None = None
        max_attempts = max(1, DIALOG_CHAT_MAX_RETRIES + 1)
        for attempt in range(1, max_attempts + 1):
            try:
                with self._session_lock:
                    session = self.session
                response = session.post(
                    f"{self.api_base}/chat/completions",
                    json=payload,
                    timeout=(DIALOG_CHAT_CONNECT_TIMEOUT_SECONDS, DIALOG_CHAT_TIMEOUT_SECONDS),
                )
                if response.status_code >= 400:
                    if response.status_code in {408, 409, 425, 429, 500, 502, 503, 504}:
                        last_error = DialogChatError(
                            f"dialog chat model HTTP {response.status_code}: {response.text}"
                        )
                        if attempt < max_attempts:
                            time.sleep(0.45 * attempt)
                            continue
                    raise DialogChatError(
                        f"dialog chat model HTTP {response.status_code}: {response.text}"
                    )
                return response.json()
            except requests.RequestException as exc:
                last_error = exc
                if attempt < max_attempts:
                    logger.info("对话模型连接异常，重建连接池后重试: %s", exc)
                    self._reset_session()
                    time.sleep(0.45 * attempt)
        raise DialogChatError(f"dialog chat model request failed after retries: {last_error}")

    def _stream_chat_completion(self, payload: dict) -> Iterator[str]:
        last_error: Exception | None = None
        max_attempts = max(1, DIALOG_CHAT_MAX_RETRIES + 1)
        for attempt in range(1, max_attempts + 1):
            try:
                with self._session_lock:
                    session = self.session
                response = session.post(
                    f"{self.api_base}/chat/completions",
                    json=payload,
                    stream=True,
                    timeout=(DIALOG_CHAT_CONNECT_TIMEOUT_SECONDS, DIALOG_CHAT_TIMEOUT_SECONDS),
                )
                if response.status_code >= 400:
                    text = response.text
                    response.close()
                    raise DialogChatError(f"dialog chat model HTTP {response.status_code}: {text}")

                with response:
                    for raw_line in response.iter_lines(decode_unicode=True):
                        if not raw_line:
                            continue
                        line = raw_line.strip()
                        if line.startswith("data:"):
                            line = line[5:].strip()
                        if not line or line == "[DONE]":
                            continue
                        try:
                            data = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        choices = data.get("choices") or []
                        if not choices:
                            continue
                        delta = choices[0].get("delta") or {}
                        token = delta.get("content") or ""
                        if token:
                            yield token
                return
            except requests.RequestException as exc:
                last_error = exc
                if attempt < max_attempts:
                    logger.info("对话模型流式连接异常，重建连接池后重试: %s", exc)
                    self._reset_session()
                    time.sleep(0.45 * attempt)
                    continue
            except DialogChatError as exc:
                last_error = exc
                if attempt < max_attempts:
                    time.sleep(0.45 * attempt)
                    continue
        raise DialogChatError(f"dialog chat model stream failed after retries: {last_error}")


_dialog_chat_service: DialogChatService | None = None


def get_dialog_chat_service() -> DialogChatService:
    global _dialog_chat_service
    if _dialog_chat_service is None:
        _dialog_chat_service = DialogChatService()
    return _dialog_chat_service


def extract_latest_user_query(text: str) -> str:
    text = (text or "").strip()
    marker = "用户最新问题:"
    if marker in text:
        latest = text.rsplit(marker, 1)[-1].strip()
        if latest:
            return latest
    return text


def classify_local_quick_reply_scene(
    text: str,
    *,
    persona=None,
) -> LocalQuickReplyScene | None:
    latest_query = extract_latest_user_query(text or "")
    query = re.sub(r"\s+", "", latest_query)
    query = re.sub(r"[，。！？,.!?;；:：、]+$", "", query)
    if not query:
        return None
    if is_assistant_identity_query(query):
        return None
    wake = parse_wake_name(
        latest_query,
        assistant_name=getattr(persona, "assistant_name", None),
        wake_aliases=getattr(persona, "wake_aliases", None),
    )
    if wake.called and wake.wake_only:
        logger.info(
            "文本对话唤名快速回复: assistant=%s alias=%s query=%s",
            wake.assistant_name,
            wake.matched_alias,
            latest_query,
        )
        return LocalQuickReplyScene(
            "assistant_wake",
            VOICE_ASSISTANT_WAKE_REPLY,
            "回应用户正在叫你，让对方知道你在听。",
            ("不要展开介绍自己。",),
        )
    if re.fullmatch(r"(你好|您好|哈喽|hello|hi|嗨)", query, re.IGNORECASE):
        return LocalQuickReplyScene(
            "casual_greeting",
            "你好，我在呢。",
            "自然打招呼并表示可以继续交流。",
        )
    if re.fullmatch(r"(谢谢|多谢|辛苦了)", query):
        return LocalQuickReplyScene(
            "thanks_reply",
            "不客气。",
            "自然回应感谢。",
        )
    if re.fullmatch(r"(好的|好|可以|可以了|行|ok|OK)", query):
        return LocalQuickReplyScene(
            "acknowledgement",
            "好的。",
            "简短确认已收到。",
        )
    if re.fullmatch(r"(再见|拜拜)", query):
        return LocalQuickReplyScene(
            "farewell",
            "好的，待会儿见。",
            "自然道别。",
        )
    return None


def match_local_quick_reply(text: str, *, persona=None) -> str:
    scene = classify_local_quick_reply_scene(text, persona=persona)
    return scene.canonical_text if scene else ""

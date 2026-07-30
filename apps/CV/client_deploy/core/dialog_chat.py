"""Text chat backend for the avatar voice demo."""

from __future__ import annotations

import logging
import json
import threading
import time
from collections.abc import Iterator

import requests
from requests.adapters import HTTPAdapter

from config import (
    DIALOG_CHAT_API_BASE,
    DIALOG_CHAT_API_KEY,
    DIALOG_CHAT_CONNECT_TIMEOUT_SECONDS,
    DIALOG_CHAT_MAX_RETRIES,
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
)
from core.knowledge.models import SearchResult
from core.knowledge.service import KnowledgeService

logger = logging.getLogger(__name__)


class DialogChatError(RuntimeError):
    pass


class DialogChatService:
    def __init__(self):
        self.api_base = DIALOG_CHAT_API_BASE
        self.api_key = DIALOG_CHAT_API_KEY
        self.model = DIALOG_CHAT_MODEL
        self.rag_enabled = DIALOG_CHAT_RAG_ENABLED
        self._session_lock = threading.RLock()
        self.session = self._build_session()

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        adapter = HTTPAdapter(
            pool_connections=4,
            pool_maxsize=16,
            max_retries=0,
            pool_block=False,
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

    def reply(self, text: str) -> dict:
        text = (text or "").strip()
        if not text:
            raise DialogChatError("text is required")
        if not self.ready:
            raise DialogChatError("dialog chat model is not configured")

        messages, sources = self._build_messages(text)
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": DIALOG_CHAT_TEMPERATURE,
        }
        data = self._post_chat_completion(payload)

        answer = data["choices"][0]["message"]["content"].strip()
        return {"text": text, "answer": answer, "model": self.model, "sources": sources}

    def stream_reply(self, text: str) -> Iterator[str]:
        text = (text or "").strip()
        if not text:
            raise DialogChatError("text is required")
        if not self.ready:
            raise DialogChatError("dialog chat model is not configured")

        payload = {
            "model": self.model,
            "messages": self._build_messages(text)[0],
            "temperature": DIALOG_CHAT_TEMPERATURE,
            "stream": True,
        }
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

    def _build_messages(self, text: str) -> tuple[list[dict[str, str]], list[dict]]:
        if not self.rag_enabled:
            return self._plain_messages(text), []

        try:
            results = KnowledgeService().search(
                text,
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
                {"role": "system", "content": DIALOG_CHAT_SYSTEM_PROMPT},
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

        sources = [KnowledgeService._result_to_dict(item) for item in results]
        context = self._format_rag_context(results)
        return [
            {
                "role": "system",
                "content": (
                    f"{DIALOG_CHAT_SYSTEM_PROMPT}\n"
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

    def _plain_messages(self, text: str) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": DIALOG_CHAT_SYSTEM_PROMPT},
            {"role": "user", "content": text},
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

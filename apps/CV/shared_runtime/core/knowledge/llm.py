"""Grounded answer generation with an OpenAI-compatible chat API."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from core.knowledge.models import SearchResult


class KnowledgeAnswerClient:
    def __init__(
        self,
        api_base: str,
        api_key: str,
        model: str,
        timeout_seconds: float,
        temperature: float,
        max_context_chars: int,
    ):
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.temperature = temperature
        self.max_context_chars = max_context_chars

    @property
    def ready(self) -> bool:
        return bool(self.api_base and self.api_key and self.model)

    def answer(self, question: str, results: list[SearchResult]) -> str:
        if not self.ready:
            raise RuntimeError("knowledge answer model is not configured")
        context = self._build_context(results)
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是公司内部知识库问答助手。必须只根据给定资料回答；"
                        "资料不足时明确说没有找到可靠依据。回答要简洁、准确，"
                        "最后给出引用来源编号。"
                    ),
                },
                {
                    "role": "user",
                    "content": f"问题：{question}\n\n知识库资料：\n{context}",
                },
            ],
            "temperature": self.temperature,
        }
        req = urllib.request.Request(
            f"{self.api_base}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"knowledge answer model HTTP {exc.code}: {body}") from exc
        return data["choices"][0]["message"]["content"].strip()

    def _build_context(self, results: list[SearchResult]) -> str:
        parts = []
        used = 0
        for index, result in enumerate(results, start=1):
            text = result.content.strip()
            header = (
                f"[{index}] 来源: {result.title}; "
                f"片段: {result.chunk_index + 1}; 路径: {result.source_path}\n"
            )
            remaining = self.max_context_chars - used - len(header)
            if remaining <= 0:
                break
            if len(text) > remaining:
                text = text[:remaining]
            parts.append(f"{header}{text}")
            used += len(header) + len(text)
        return "\n\n".join(parts)

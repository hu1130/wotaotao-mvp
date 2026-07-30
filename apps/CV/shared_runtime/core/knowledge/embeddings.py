"""Embedding client for the PostgreSQL-backed knowledge retriever."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)


class KnowledgeEmbeddingError(RuntimeError):
    pass


class KnowledgeEmbeddingClient:
    """Small OpenAI-compatible embeddings client.

    The app already uses OpenAI-compatible chat endpoints for knowledge answers,
    so the retrieval layer keeps the same integration shape and only requires a
    model that returns fixed-size text embeddings.
    """

    def __init__(
        self,
        api_base: str,
        api_key: str,
        model: str,
        dimension: int,
        timeout_seconds: float,
        batch_size: int,
    ):
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.dimension = dimension
        self.timeout_seconds = timeout_seconds
        self.batch_size = max(1, batch_size)

    @property
    def ready(self) -> bool:
        return bool(self.api_base and self.api_key and self.model and self.dimension > 0)

    def embed_query(self, text: str) -> list[float]:
        vectors = self.embed_texts([text])
        if not vectors:
            raise KnowledgeEmbeddingError("embedding API returned no query vector")
        return vectors[0]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        texts = [item.strip() for item in texts if item and item.strip()]
        if not texts:
            return []
        if not self.ready:
            raise KnowledgeEmbeddingError(
                "knowledge embedding model is not configured; set KNOWLEDGE_EMBEDDING_*"
            )

        all_vectors: list[list[float]] = []
        for offset in range(0, len(texts), self.batch_size):
            batch = texts[offset : offset + self.batch_size]
            vectors = self._request_batch(batch)
            all_vectors.extend(vectors)
            logger.debug(
                "知识库 embedding 批次完成: offset=%d size=%d dim=%d",
                offset,
                len(batch),
                self.dimension,
            )
        return all_vectors

    def _request_batch(self, texts: list[str]) -> list[list[float]]:
        payload = {
            "model": self.model,
            "input": texts,
            "dimensions": self.dimension,
        }
        req = urllib.request.Request(
            f"{self.api_base}/embeddings",
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
            raise KnowledgeEmbeddingError(f"embedding API HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise KnowledgeEmbeddingError(f"embedding API request failed: {exc}") from exc

        items = sorted(data.get("data", []), key=lambda item: item.get("index", 0))
        vectors = [item.get("embedding") for item in items]
        if len(vectors) != len(texts):
            raise KnowledgeEmbeddingError(
                f"embedding API returned {len(vectors)} vectors for {len(texts)} texts"
            )
        normalized: list[list[float]] = []
        for index, vector in enumerate(vectors):
            if not isinstance(vector, list):
                raise KnowledgeEmbeddingError(f"embedding #{index} is not a list")
            if len(vector) != self.dimension:
                raise KnowledgeEmbeddingError(
                    f"embedding dimension mismatch: expected {self.dimension}, got {len(vector)}"
                )
            normalized.append([float(value) for value in vector])
        return normalized

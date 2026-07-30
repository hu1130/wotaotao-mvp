"""Application service for local knowledge indexing, search, and answering."""

from __future__ import annotations

from pathlib import Path

from config import (
    KNOWLEDGE_ALLOWED_ROOTS,
    KNOWLEDGE_ANSWER_API_BASE,
    KNOWLEDGE_ANSWER_API_KEY,
    KNOWLEDGE_ANSWER_MODEL,
    KNOWLEDGE_ANSWER_TEMPERATURE,
    KNOWLEDGE_ANSWER_TIMEOUT_SECONDS,
    KNOWLEDGE_BASE_DIR,
    KNOWLEDGE_CHUNK_OVERLAP,
    KNOWLEDGE_CHUNK_SIZE,
    KNOWLEDGE_EMBEDDING_API_BASE,
    KNOWLEDGE_EMBEDDING_API_KEY,
    KNOWLEDGE_EMBEDDING_BATCH_SIZE,
    KNOWLEDGE_EMBEDDING_DIM,
    KNOWLEDGE_EMBEDDING_MODEL,
    KNOWLEDGE_EMBEDDING_TIMEOUT_SECONDS,
    KNOWLEDGE_MAX_CONTEXT_CHARS,
    KNOWLEDGE_MIN_SCORE,
    KNOWLEDGE_SEARCH_TOP_K,
    TENANT_ID,
)
from core.knowledge.chunking import chunk_document
from core.knowledge.embeddings import KnowledgeEmbeddingClient
from core.knowledge.llm import KnowledgeAnswerClient
from core.knowledge.loaders import iter_documents
from core.knowledge.models import SearchResult
from core.knowledge.store import KnowledgeStore
from core.tenant import DEFAULT_TENANT_ID, normalize_tenant_id


class KnowledgeError(RuntimeError):
    pass


class KnowledgeService:
    def __init__(self, tenant_id: str = TENANT_ID):
        self.tenant_id = normalize_tenant_id(tenant_id)
        self.embedding_client = KnowledgeEmbeddingClient(
            api_base=KNOWLEDGE_EMBEDDING_API_BASE,
            api_key=KNOWLEDGE_EMBEDDING_API_KEY,
            model=KNOWLEDGE_EMBEDDING_MODEL,
            dimension=KNOWLEDGE_EMBEDDING_DIM,
            timeout_seconds=KNOWLEDGE_EMBEDDING_TIMEOUT_SECONDS,
            batch_size=KNOWLEDGE_EMBEDDING_BATCH_SIZE,
        )
        self.store = KnowledgeStore(
            embedding_client=self.embedding_client,
            embedding_dim=KNOWLEDGE_EMBEDDING_DIM,
            tenant_id=self.tenant_id,
        )
        self.answer_client = KnowledgeAnswerClient(
            api_base=KNOWLEDGE_ANSWER_API_BASE,
            api_key=KNOWLEDGE_ANSWER_API_KEY,
            model=KNOWLEDGE_ANSWER_MODEL,
            timeout_seconds=KNOWLEDGE_ANSWER_TIMEOUT_SECONDS,
            temperature=KNOWLEDGE_ANSWER_TEMPERATURE,
            max_context_chars=KNOWLEDGE_MAX_CONTEXT_CHARS,
        )

    def index_paths(self, paths: list[str] | None = None, reset: bool = False) -> dict:
        raw_paths = paths or [str(self._default_tenant_root())]
        safe_paths = [self._validate_path(path) for path in raw_paths]
        documents = [
            document
            for document in iter_documents(safe_paths)
            if self._document_allowed(document.source_path)
        ]
        chunks = []
        for document in documents:
            chunks.extend(
                chunk_document(
                    document,
                    chunk_size=KNOWLEDGE_CHUNK_SIZE,
                    overlap=KNOWLEDGE_CHUNK_OVERLAP,
                )
            )
        if reset:
            self.store.reset()
        chunk_count = self.store.upsert_chunks(chunks)
        return {
            "tenantId": self.tenant_id,
            "documents": len(documents),
            "chunks": chunk_count,
            "stats": self.store.stats(),
        }

    def search(
        self,
        query: str,
        top_k: int | None = None,
        min_score: float | None = None,
    ) -> list[SearchResult]:
        query = (query or "").strip()
        if not query:
            raise KnowledgeError("query is required")
        return self.store.search(
            query,
            top_k=top_k or KNOWLEDGE_SEARCH_TOP_K,
            min_score=KNOWLEDGE_MIN_SCORE if min_score is None else min_score,
        )

    def answer(self, question: str, top_k: int | None = None) -> dict:
        results = self.search(question, top_k=top_k)
        if not results:
            return {
                "answer": "知识库里没有找到足够可靠的依据，暂时不能基于本地资料回答这个问题。",
                "sources": [],
                "model": None,
            }
        answer = self.answer_client.answer(question, results)
        return {
            "answer": answer,
            "sources": [self._result_to_dict(item) for item in results],
            "model": KNOWLEDGE_ANSWER_MODEL,
        }

    def stats(self) -> dict:
        return self.store.stats()

    def _validate_path(self, raw_path: str) -> str:
        path = Path(raw_path).expanduser().resolve()
        tenant_root = self._tenant_root().resolve()
        if self.tenant_id != DEFAULT_TENANT_ID:
            tenant_root.mkdir(parents=True, exist_ok=True)
            if path != tenant_root and tenant_root not in path.parents:
                raise KnowledgeError(
                    f"knowledge path is outside tenant root: {path}; tenant_root: {tenant_root}"
                )
        allowed_roots = [Path(root).expanduser().resolve() for root in KNOWLEDGE_ALLOWED_ROOTS]
        if not allowed_roots:
            raise KnowledgeError("KNOWLEDGE_ALLOWED_ROOTS is empty")
        for root in allowed_roots:
            if path == root or root in path.parents:
                return str(path)
        roots = "; ".join(str(root) for root in allowed_roots)
        raise KnowledgeError(f"knowledge path is outside allowed roots: {path}; allowed: {roots}")

    def _default_tenant_root(self) -> Path:
        if self.tenant_id == DEFAULT_TENANT_ID:
            return Path(KNOWLEDGE_BASE_DIR)
        return self._tenant_root()

    def _tenant_root(self) -> Path:
        return Path(KNOWLEDGE_BASE_DIR) / "tenants" / self.tenant_id

    def _document_allowed(self, source_path: str) -> bool:
        source = Path(source_path).expanduser().resolve()
        tenants_root = (Path(KNOWLEDGE_BASE_DIR) / "tenants").resolve()
        if tenants_root not in source.parents:
            return self.tenant_id == DEFAULT_TENANT_ID
        tenant_root = self._tenant_root().resolve()
        return source == tenant_root or tenant_root in source.parents

    @staticmethod
    def _result_to_dict(result: SearchResult) -> dict:
        return {
            "chunkId": result.chunk_id,
            "sourcePath": result.source_path,
            "title": result.title,
            "chunkIndex": result.chunk_index,
            "score": result.score,
            "citation": result.citation_label(),
            "content": result.content,
            "metadata": result.metadata,
        }

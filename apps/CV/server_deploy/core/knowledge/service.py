"""Application service for local knowledge indexing, search, and answering."""

from __future__ import annotations

import hashlib
from pathlib import Path
import re
import threading

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
)
from core.knowledge.chunking import chunk_document
from core.knowledge.embeddings import KnowledgeEmbeddingClient
from core.knowledge.llm import KnowledgeAnswerClient
from core.knowledge.loaders import SUPPORTED_EXTENSIONS, load_document
from core.knowledge.models import SearchResult
from core.knowledge.store import KnowledgeStore
from core.tenant import DEFAULT_TENANT_ID, normalize_tenant_id


class KnowledgeError(RuntimeError):
    pass


class KnowledgeService:
    def __init__(self, tenant_id: str = DEFAULT_TENANT_ID):
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
        source_paths = [
            path
            for path in self._iter_document_paths(safe_paths)
            if self._document_allowed(str(path))
        ]
        fingerprints = {
            str(path): self._file_fingerprint(path)
            for path in source_paths
        }
        if reset:
            self.store.reset()
            changed_paths = source_paths
            skipped_sources: list[str] = []
            removed_sources = 0
        else:
            stored = self.store.get_document_fingerprints(list(fingerprints.keys()))
            changed_paths = [
                path
                for path in source_paths
                if stored.get(str(path), {}).get("contentHash") != fingerprints[str(path)]["contentHash"]
            ]
            skipped_sources = [
                str(path)
                for path in source_paths
                if path not in changed_paths
            ]
            removed_sources = self.store.delete_missing_sources(
                active_source_paths=list(fingerprints.keys()),
                scope_paths=safe_paths,
            )

        changed_source_paths = {str(path) for path in changed_paths}
        documents = [load_document(path) for path in changed_paths]
        chunks = []
        for document in documents:
            chunks.extend(
                chunk_document(
                    document,
                    chunk_size=KNOWLEDGE_CHUNK_SIZE,
                    overlap=KNOWLEDGE_CHUNK_OVERLAP,
                )
            )
        chunk_count = self.store.upsert_chunks(
            chunks,
            document_metadata={
                source_path: {
                    "contentHash": metadata["contentHash"],
                    "contentBytes": metadata["contentBytes"],
                }
                for source_path, metadata in fingerprints.items()
                if source_path in changed_source_paths
            },
        )
        return {
            "tenantId": self.tenant_id,
            "documents": len(source_paths),
            "indexedDocuments": len(documents),
            "skippedDocuments": len(skipped_sources),
            "removedDocuments": removed_sources,
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
        search_query = expand_company_overview_query(query)
        return self.store.search(
            search_query,
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

    def _iter_document_paths(self, paths: list[str]) -> list[Path]:
        documents: list[Path] = []
        for raw_path in paths:
            path = Path(raw_path).expanduser().resolve()
            if path.is_dir():
                for child in sorted(path.rglob("*")):
                    if child.is_file() and child.suffix.lower() in SUPPORTED_EXTENSIONS:
                        documents.append(child.resolve())
            elif path.is_file():
                if path.suffix.lower() in SUPPORTED_EXTENSIONS:
                    documents.append(path)
            else:
                raise FileNotFoundError(f"knowledge path not found: {path}")
        return list(dict.fromkeys(documents))

    @staticmethod
    def _file_fingerprint(path: Path) -> dict[str, object]:
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as input_file:
            while True:
                chunk = input_file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                digest.update(chunk)
        return {
            "contentHash": digest.hexdigest(),
            "contentBytes": size,
        }

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


def expand_company_overview_query(query: str) -> str:
    normalized = re.sub(r"\s+", "", query or "")
    if not normalized:
        return query
    company_terms = ("公司", "企业", "你们", "你公司", "深度觉醒")
    overview_terms = (
        "干什么",
        "做什么",
        "是做啥",
        "业务",
        "产品",
        "介绍",
        "定位",
        "主营",
        "服务",
    )
    if any(term in normalized for term in company_terms) and any(
        term in normalized for term in overview_terms
    ):
        expansion = "深度觉醒 产品 定位 核心产品矩阵 AI赋能 企业 定制化服务 提效工具 智能系统"
        if expansion not in query:
            return f"{query} {expansion}"
    return query


_services: dict[str, KnowledgeService] = {}
_services_lock = threading.Lock()


def get_knowledge_service(
    tenant_id: str = DEFAULT_TENANT_ID,
) -> KnowledgeService:
    tenant_id = normalize_tenant_id(tenant_id)
    service = _services.get(tenant_id)
    if service is not None:
        return service
    with _services_lock:
        return _services.setdefault(tenant_id, KnowledgeService(tenant_id))

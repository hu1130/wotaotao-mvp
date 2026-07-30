"""PostgreSQL + pgvector knowledge index with hybrid retrieval."""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path
import re
import time
from contextlib import contextmanager

import psycopg2
from pgvector.psycopg2 import register_vector
from psycopg2 import sql
from psycopg2.pool import ThreadedConnectionPool

from config import (
    KNOWLEDGE_HNSW_EF_CONSTRUCTION,
    KNOWLEDGE_HNSW_M,
    KNOWLEDGE_HYBRID_CANDIDATES,
    KNOWLEDGE_HYBRID_LEXICAL_WEIGHT,
    KNOWLEDGE_HYBRID_RRF_K,
    KNOWLEDGE_HYBRID_VECTOR_WEIGHT,
    PG_DATABASE,
    PG_HOST,
    PG_PASSWORD,
    PG_POOL_SIZE,
    PG_PORT,
    PG_USER,
)
from core.knowledge.embeddings import KnowledgeEmbeddingClient
from core.knowledge.models import KnowledgeChunk, SearchResult
from core.tenant import DEFAULT_TENANT_ID, normalize_tenant_id

logger = logging.getLogger(__name__)

DOCUMENTS_TABLE = "knowledge_documents"
CHUNKS_TABLE = "knowledge_chunks"
POOL_CONNECTION_RETRIES = 2


class KnowledgeStore:
    """Stores knowledge chunks in PostgreSQL and retrieves by hybrid ranking."""

    def __init__(
        self,
        embedding_client: KnowledgeEmbeddingClient,
        embedding_dim: int,
        tenant_id: str = DEFAULT_TENANT_ID,
    ):
        self.tenant_id = normalize_tenant_id(tenant_id)
        self.embedding_client = embedding_client
        self.embedding_dim = embedding_dim
        conn = self._create_conn()
        try:
            self._ensure_db(conn)
        finally:
            conn.close()
        self._pool = ThreadedConnectionPool(
            1,
            max(1, PG_POOL_SIZE),
            **self._connect_kwargs(PG_DATABASE),
        )
        self._init_schema()

    def reset(self) -> None:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"DELETE FROM {CHUNKS_TABLE} WHERE tenant_id = %s",
                    (self.tenant_id,),
                )
                cur.execute(
                    f"DELETE FROM {DOCUMENTS_TABLE} WHERE tenant_id = %s",
                    (self.tenant_id,),
                )
        logger.info(
            "知识库索引已清空: tenant=%s tables=%s,%s",
            self.tenant_id,
            DOCUMENTS_TABLE,
            CHUNKS_TABLE,
        )

    def get_document_fingerprints(self, source_paths: list[str]) -> dict[str, dict[str, object]]:
        if not source_paths:
            return {}
        with self._connection(register_pgvector=False) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT source_path, content_hash, content_bytes
                    FROM {DOCUMENTS_TABLE}
                    WHERE tenant_id = %s AND source_path = ANY(%s)
                    """,
                    (self.tenant_id, source_paths),
                )
                rows = cur.fetchall()
        return {
            str(row[0]): {
                "contentHash": str(row[1] or ""),
                "contentBytes": int(row[2] or 0),
            }
            for row in rows
        }

    def delete_missing_sources(
        self,
        *,
        active_source_paths: list[str],
        scope_paths: list[str],
    ) -> int:
        active_sources = {str(Path(path).resolve()) for path in active_source_paths}
        scopes = [Path(path).resolve() for path in scope_paths]
        if not scopes:
            return 0

        with self._connection(register_pgvector=False) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT source_path
                    FROM {DOCUMENTS_TABLE}
                    WHERE tenant_id = %s
                    """,
                    (self.tenant_id,),
                )
                rows = cur.fetchall()

                stale_sources = [
                    str(row[0])
                    for row in rows
                    if _source_in_scopes(str(row[0]), scopes)
                    and str(Path(str(row[0])).resolve()) not in active_sources
                ]
                if not stale_sources:
                    return 0
                cur.execute(
                    f"""
                    DELETE FROM {DOCUMENTS_TABLE}
                    WHERE tenant_id = %s AND source_path = ANY(%s)
                    """,
                    (self.tenant_id, stale_sources),
                )
                deleted = cur.rowcount
        logger.info(
            "知识库缺失文档索引已删除: tenant=%s documents=%d",
            self.tenant_id,
            deleted,
        )
        return int(deleted or 0)

    def upsert_chunks(
        self,
        chunks: list[KnowledgeChunk],
        *,
        document_metadata: dict[str, dict[str, object]] | None = None,
    ) -> int:
        if not chunks:
            return 0
        document_metadata = document_metadata or {}

        now = int(time.time())
        texts = [_embedding_text(chunk) for chunk in chunks]
        embeddings = self.embedding_client.embed_texts(texts)
        if len(embeddings) != len(chunks):
            raise RuntimeError(
                f"knowledge embedding count mismatch: chunks={len(chunks)} vectors={len(embeddings)}"
            )

        by_source: dict[str, list[tuple[KnowledgeChunk, list[float]]]] = {}
        for chunk, embedding in zip(chunks, embeddings):
            by_source.setdefault(chunk.source_path, []).append((chunk, embedding))

        with self._connection() as conn:
            with conn.cursor() as cur:
                for source_path, source_chunks in by_source.items():
                    first = source_chunks[0][0]
                    cur.execute(
                        f"DELETE FROM {CHUNKS_TABLE} "
                        "WHERE tenant_id = %s AND source_path = %s",
                        (self.tenant_id, source_path),
                    )
                    cur.execute(
                        f"DELETE FROM {DOCUMENTS_TABLE} "
                        "WHERE tenant_id = %s AND source_path = %s",
                        (self.tenant_id, source_path),
                    )
                    cur.execute(
                        f"""
                        INSERT INTO {DOCUMENTS_TABLE}(
                            tenant_id, source_path, title, metadata_json, updated_at,
                            content_hash, content_bytes, indexed_at
                        )
                        VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s, %s)
                        """,
                        (
                            self.tenant_id,
                            source_path,
                            first.title,
                            json.dumps(first.metadata, ensure_ascii=False),
                            now,
                            str(document_metadata.get(source_path, {}).get("contentHash") or ""),
                            int(document_metadata.get(source_path, {}).get("contentBytes") or 0),
                            now,
                        ),
                    )
                    rows = [
                        (
                            self.tenant_id,
                            item.source_path,
                            item.title,
                            item.chunk_index,
                            item.content,
                            json.dumps(item.metadata, ensure_ascii=False),
                            " ".join(_tokenize(f"{item.title} {item.content}")),
                            embedding,
                        )
                        for item, embedding in source_chunks
                    ]
                    cur.executemany(
                        f"""
                        INSERT INTO {CHUNKS_TABLE}(
                            tenant_id, source_path, title, chunk_index, content,
                            metadata_json, tokens, embedding
                        )
                        VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s)
                        """,
                        rows,
                    )
                    logger.info(
                        "知识库文档索引完成: source=%s chunks=%d",
                        source_path,
                        len(source_chunks),
                    )

        logger.info(
            "知识库 pgvector 索引写入完成: documents=%d chunks=%d dim=%d",
            len(by_source),
            len(chunks),
            self.embedding_dim,
        )
        return len(chunks)

    def search(self, query: str, top_k: int, min_score: float = 0.0) -> list[SearchResult]:
        query = (query or "").strip()
        if not query:
            return []

        query_embedding = self.embedding_client.embed_query(query)
        query_tokens = " ".join(_tokenize(query))
        candidate_limit = max(top_k, KNOWLEDGE_HYBRID_CANDIDATES)

        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT set_config('hnsw.ef_search', %s, true)
                    """,
                    (str(max(candidate_limit, 40)),),
                )
                cur.execute(
                    f"""
                    WITH
                    vector_ranked AS (
                        SELECT
                            id,
                            row_number() OVER (ORDER BY embedding <=> %s::vector) AS vector_rank,
                            1 - (embedding <=> %s::vector) AS vector_score
                        FROM {CHUNKS_TABLE}
                        WHERE tenant_id = %s AND embedding IS NOT NULL
                        ORDER BY embedding <=> %s::vector
                        LIMIT %s
                    ),
                    lexical_ranked AS (
                        SELECT
                            id,
                            row_number() OVER (
                                ORDER BY ts_rank_cd(
                                    to_tsvector('simple', tokens),
                                    plainto_tsquery('simple', %s)
                                ) DESC
                            ) AS lexical_rank,
                            ts_rank_cd(
                                to_tsvector('simple', tokens),
                                plainto_tsquery('simple', %s)
                            ) AS lexical_score
                        FROM {CHUNKS_TABLE}
                        WHERE
                            tenant_id = %s
                            AND %s <> ''
                            AND to_tsvector('simple', tokens) @@ plainto_tsquery('simple', %s)
                        ORDER BY lexical_score DESC
                        LIMIT %s
                    ),
                    merged AS (
                        SELECT
                            COALESCE(v.id, l.id) AS id,
                            v.vector_rank,
                            COALESCE(v.vector_score, 0.0) AS vector_score,
                            l.lexical_rank,
                            COALESCE(l.lexical_score, 0.0) AS lexical_score,
                            (
                                CASE
                                    WHEN v.vector_rank IS NULL THEN 0.0
                                    ELSE %s
                                        * GREATEST(v.vector_score, 0.0)
                                        * (%s / (%s + v.vector_rank))
                                END
                                +
                                CASE
                                    WHEN l.lexical_rank IS NULL THEN 0.0
                                    ELSE %s * (%s / (%s + l.lexical_rank))
                                END
                            ) AS hybrid_score
                        FROM vector_ranked v
                        FULL OUTER JOIN lexical_ranked l ON v.id = l.id
                    )
                    SELECT
                        c.id,
                        c.source_path,
                        c.title,
                        c.content,
                        c.chunk_index,
                        c.metadata_json::text,
                        merged.hybrid_score,
                        merged.vector_score,
                        merged.lexical_score,
                        merged.vector_rank,
                        merged.lexical_rank
                    FROM merged
                    JOIN {CHUNKS_TABLE} c ON c.id = merged.id
                    WHERE merged.hybrid_score >= %s
                    ORDER BY merged.hybrid_score DESC, merged.vector_score DESC
                    LIMIT %s
                    """,
                    (
                        query_embedding,
                        query_embedding,
                        self.tenant_id,
                        query_embedding,
                        candidate_limit,
                        query_tokens,
                        query_tokens,
                        self.tenant_id,
                        query_tokens,
                        query_tokens,
                        candidate_limit,
                        KNOWLEDGE_HYBRID_VECTOR_WEIGHT,
                        KNOWLEDGE_HYBRID_RRF_K,
                        KNOWLEDGE_HYBRID_RRF_K,
                        KNOWLEDGE_HYBRID_LEXICAL_WEIGHT,
                        KNOWLEDGE_HYBRID_RRF_K,
                        KNOWLEDGE_HYBRID_RRF_K,
                        min_score,
                        max(1, top_k),
                    ),
                )
                rows = cur.fetchall()

        results = [
            SearchResult(
                chunk_id=int(row[0]),
                source_path=row[1],
                title=row[2],
                content=row[3],
                score=round(float(row[6]), 4),
                chunk_index=int(row[4]),
                metadata=_metadata_with_scores(
                    row[5],
                    vector_score=row[7],
                    lexical_score=row[8],
                    vector_rank=row[9],
                    lexical_rank=row[10],
                ),
            )
            for row in rows
        ]
        logger.info(
            "知识库混合检索完成: query=%r top_k=%d candidates=%d results=%d min_score=%.4f",
            query,
            top_k,
            candidate_limit,
            len(results),
            min_score,
        )
        return results

    def stats(self) -> dict:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT COUNT(*) FROM {DOCUMENTS_TABLE} WHERE tenant_id = %s",
                    (self.tenant_id,),
                )
                documents = cur.fetchone()[0]
                cur.execute(
                    f"SELECT COUNT(*) FROM {CHUNKS_TABLE} WHERE tenant_id = %s",
                    (self.tenant_id,),
                )
                chunks = cur.fetchone()[0]
                cur.execute(
                    f"SELECT MAX(updated_at) FROM {DOCUMENTS_TABLE} WHERE tenant_id = %s",
                    (self.tenant_id,),
                )
                updated_at = cur.fetchone()[0]
        return {
            "tenantId": self.tenant_id,
            "documents": documents,
            "chunks": chunks,
            "updatedAt": updated_at,
            "backend": "postgresql+pgvector+hnsw+hybrid",
            "embeddingDim": self.embedding_dim,
        }

    @staticmethod
    def _connect_kwargs(database: str | None = None) -> dict:
        kwargs = dict(
            host=PG_HOST,
            port=PG_PORT,
            user=PG_USER,
            password=PG_PASSWORD,
            connect_timeout=10,
            keepalives=1,
            keepalives_idle=30,
            keepalives_interval=10,
            keepalives_count=3,
        )
        if database:
            kwargs["dbname"] = database
        return kwargs

    @staticmethod
    def _create_conn(database: str | None = None) -> psycopg2.extensions.connection:
        conn = psycopg2.connect(**KnowledgeStore._connect_kwargs(database))
        conn.autocommit = True
        return conn

    @staticmethod
    def _prepare_connection(conn: psycopg2.extensions.connection) -> bool:
        if conn.closed:
            return False
        try:
            if conn.status != psycopg2.extensions.STATUS_READY:
                conn.rollback()
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
            return True
        except psycopg2.Error:
            return False

    @contextmanager
    def _connection(self, register_pgvector: bool = True):
        conn = None
        close_conn = False
        try:
            for attempt in range(POOL_CONNECTION_RETRIES):
                conn = self._pool.getconn()
                if self._prepare_connection(conn):
                    break
                self._pool.putconn(conn, close=True)
                conn = None
                if attempt == POOL_CONNECTION_RETRIES - 1:
                    raise psycopg2.OperationalError("knowledge pgvector connection is not usable")

            if register_pgvector:
                register_vector(conn)
            yield conn
        except psycopg2.Error:
            close_conn = True
            raise
        finally:
            if conn is not None:
                self._pool.putconn(conn, close=close_conn)

    def _ensure_db(self, conn):
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (PG_DATABASE,))
            if cur.fetchone() is None:
                cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(PG_DATABASE)))

    def _init_schema(self) -> None:
        with self._connection(register_pgvector=False) as conn:
            with conn.cursor() as cur:
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
                register_vector(conn)
                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {DOCUMENTS_TABLE} (
                        tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
                        source_path TEXT NOT NULL,
                        title TEXT NOT NULL,
                        metadata_json JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                        updated_at INTEGER NOT NULL,
                        CONSTRAINT {DOCUMENTS_TABLE}_tenant_source_pkey
                            PRIMARY KEY (tenant_id, source_path)
                    )
                    """
                )
                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {CHUNKS_TABLE} (
                        id BIGSERIAL PRIMARY KEY,
                        tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
                        source_path TEXT NOT NULL,
                        title TEXT NOT NULL,
                        chunk_index INTEGER NOT NULL,
                        content TEXT NOT NULL,
                        metadata_json JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                        tokens TEXT NOT NULL DEFAULT '',
                        embedding vector({self.embedding_dim}) NOT NULL,
                        created_at TIMESTAMP DEFAULT NOW(),
                        CONSTRAINT {CHUNKS_TABLE}_tenant_source_chunk_key
                            UNIQUE (tenant_id, source_path, chunk_index),
                        CONSTRAINT {CHUNKS_TABLE}_tenant_source_fkey
                            FOREIGN KEY (tenant_id, source_path)
                            REFERENCES {DOCUMENTS_TABLE}(tenant_id, source_path)
                            ON DELETE CASCADE
                    )
                    """
                )
                cur.execute(
                    f"ALTER TABLE {DOCUMENTS_TABLE} ADD COLUMN IF NOT EXISTS "
                    "tenant_id VARCHAR(64) NOT NULL DEFAULT 'default'"
                )
                cur.execute(
                    f"ALTER TABLE {CHUNKS_TABLE} ADD COLUMN IF NOT EXISTS "
                    "tenant_id VARCHAR(64) NOT NULL DEFAULT 'default'"
                )
                cur.execute(
                    f"ALTER TABLE {DOCUMENTS_TABLE} ADD COLUMN IF NOT EXISTS "
                    "content_hash TEXT NOT NULL DEFAULT ''"
                )
                cur.execute(
                    f"ALTER TABLE {DOCUMENTS_TABLE} ADD COLUMN IF NOT EXISTS "
                    "content_bytes BIGINT NOT NULL DEFAULT 0"
                )
                cur.execute(
                    f"ALTER TABLE {DOCUMENTS_TABLE} ADD COLUMN IF NOT EXISTS "
                    "indexed_at INTEGER NOT NULL DEFAULT 0"
                )
                cur.execute(
                    f"ALTER TABLE {CHUNKS_TABLE} DROP CONSTRAINT IF EXISTS "
                    f"{CHUNKS_TABLE}_source_path_fkey"
                )
                cur.execute(
                    f"ALTER TABLE {CHUNKS_TABLE} DROP CONSTRAINT IF EXISTS "
                    f"{CHUNKS_TABLE}_source_path_chunk_index_key"
                )
                cur.execute(
                    f"ALTER TABLE {DOCUMENTS_TABLE} DROP CONSTRAINT IF EXISTS "
                    f"{DOCUMENTS_TABLE}_pkey"
                )
                cur.execute(
                    f"""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM pg_constraint
                            WHERE conname = '{DOCUMENTS_TABLE}_tenant_source_pkey'
                        ) THEN
                            ALTER TABLE {DOCUMENTS_TABLE}
                            ADD CONSTRAINT {DOCUMENTS_TABLE}_tenant_source_pkey
                            PRIMARY KEY (tenant_id, source_path);
                        END IF;
                    END $$
                    """
                )
                cur.execute(
                    f"""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM pg_constraint
                            WHERE conname = '{CHUNKS_TABLE}_tenant_source_chunk_key'
                        ) THEN
                            ALTER TABLE {CHUNKS_TABLE}
                            ADD CONSTRAINT {CHUNKS_TABLE}_tenant_source_chunk_key
                            UNIQUE (tenant_id, source_path, chunk_index);
                        END IF;
                    END $$
                    """
                )
                cur.execute(
                    f"""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM pg_constraint
                            WHERE conname = '{CHUNKS_TABLE}_tenant_source_fkey'
                        ) THEN
                            ALTER TABLE {CHUNKS_TABLE}
                            ADD CONSTRAINT {CHUNKS_TABLE}_tenant_source_fkey
                            FOREIGN KEY (tenant_id, source_path)
                            REFERENCES {DOCUMENTS_TABLE}(tenant_id, source_path)
                            ON DELETE CASCADE;
                        END IF;
                    END $$
                    """
                )
                cur.execute(
                    f"""
                    CREATE INDEX IF NOT EXISTS idx_{CHUNKS_TABLE}_source
                    ON {CHUNKS_TABLE} (source_path)
                    """
                )
                cur.execute(
                    f"""
                    CREATE INDEX IF NOT EXISTS idx_{CHUNKS_TABLE}_tenant_source
                    ON {CHUNKS_TABLE} (tenant_id, source_path)
                    """
                )
                cur.execute(
                    f"""
                    CREATE INDEX IF NOT EXISTS idx_{DOCUMENTS_TABLE}_tenant_hash
                    ON {DOCUMENTS_TABLE} (tenant_id, content_hash)
                    """
                )
                cur.execute(
                    f"""
                    CREATE INDEX IF NOT EXISTS idx_{CHUNKS_TABLE}_chunk_index
                    ON {CHUNKS_TABLE} (chunk_index)
                    """
                )
                cur.execute(
                    f"""
                    CREATE INDEX IF NOT EXISTS idx_{CHUNKS_TABLE}_tokens_fts
                    ON {CHUNKS_TABLE}
                    USING gin (to_tsvector('simple', tokens))
                    """
                )
                self._create_hnsw_index(cur)
        logger.info(
            "知识库 pgvector 就绪: %s:%s/%s table=%s dim=%d",
            PG_HOST,
            PG_PORT,
            PG_DATABASE,
            CHUNKS_TABLE,
            self.embedding_dim,
        )

    def _create_hnsw_index(self, cur) -> None:
        try:
            cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_{CHUNKS_TABLE}_embedding_hnsw
                ON {CHUNKS_TABLE}
                USING hnsw (embedding vector_cosine_ops)
                WITH (m = {KNOWLEDGE_HNSW_M}, ef_construction = {KNOWLEDGE_HNSW_EF_CONSTRUCTION})
                """,
            )
        except Exception as exc:
            logger.exception("知识库 HNSW 索引创建失败，请检查 pgvector 版本: %s", exc)
            raise


def _embedding_text(chunk: KnowledgeChunk) -> str:
    metadata = " ".join(f"{key}:{value}" for key, value in sorted(chunk.metadata.items()))
    return f"{chunk.title}\n{metadata}\n{chunk.content}".strip()


def _source_in_scopes(source_path: str, scopes: list[Path]) -> bool:
    source = Path(source_path).resolve()
    for scope in scopes:
        if scope.is_file() and source == scope:
            return True
        if scope.is_dir() and (source == scope or scope in source.parents):
            return True
    return False


def _tokenize(text: str) -> list[str]:
    normalized = text.lower()
    words = re.findall(r"[a-z0-9_]{2,}|[\u4e00-\u9fff]{1,}", normalized)
    tokens: list[str] = []
    for word in words:
        if re.fullmatch(r"[\u4e00-\u9fff]+", word):
            if len(word) <= 2:
                tokens.append(word)
            else:
                tokens.extend(word[i : i + 2] for i in range(len(word) - 1))
                tokens.extend(word[i : i + 3] for i in range(len(word) - 2))
        else:
            tokens.append(word)
    return list(dict.fromkeys(tokens))


def _metadata_with_scores(
    metadata_json: str,
    *,
    vector_score,
    lexical_score,
    vector_rank,
    lexical_rank,
) -> dict:
    metadata = json.loads(metadata_json or "{}")
    metadata["retrieval"] = {
        "mode": "hybrid_pgvector_hnsw",
        "vectorScore": _round_optional(vector_score),
        "lexicalScore": _round_optional(lexical_score),
        "vectorRank": vector_rank,
        "lexicalRank": lexical_rank,
    }
    return metadata


def _round_optional(value) -> float:
    if value is None:
        return 0.0
    if isinstance(value, float) and math.isnan(value):
        return 0.0
    return round(float(value), 4)

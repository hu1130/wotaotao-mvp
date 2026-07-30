"""PostgreSQL repositories for transcripts, outbox jobs, profiles, and facts."""

from __future__ import annotations

import hashlib
import logging
import threading
import uuid
from collections.abc import Sequence
from contextlib import contextmanager

from pgvector.psycopg2 import register_vector
from psycopg2.extensions import STATUS_READY
from psycopg2.extras import Json
from psycopg2.pool import ThreadedConnectionPool

from config import (
    PERSON_MEMORY_DEBOUNCE_SECONDS,
    PERSON_MEMORY_DAILY_SUMMARY_MAX_CHARS,
    PERSON_MEMORY_DAILY_SUMMARY_MAX_TURNS,
    PERSON_MEMORY_DAILY_SUMMARY_TOP_K,
    PERSON_MEMORY_IMPLICIT_EXTRACTION_ENABLED,
    PERSON_MEMORY_EMBEDDING_MODEL,
    PERSON_MEMORY_WORKER_BATCH_SIZE,
    PERSON_MEMORY_WORKER_LEASE_SECONDS,
    PG_DATABASE,
    PG_HOST,
    PG_PASSWORD,
    PG_POOL_SIZE,
    PG_PORT,
    PG_USER,
)
from core.person_memory.migrations import run_person_memory_migrations
from core.person_memory.models import (
    DailySummaryCandidate,
    MemoryFactCandidate,
    MemoryJobBatch,
    RetrievedPersonMemory,
)
from core.person_memory.text import normalized_fact_key, tokenize
from core.tenant import DEFAULT_TENANT_ID, normalize_tenant_id

logger = logging.getLogger("uvicorn.error")

EXPLICIT_MEMORY_EXTRACTOR_VERSION = "explicit-user-command"


class PostgresPersonMemoryRepository:
    """Single durable boundary for raw dialogue and derived person memory."""

    def __init__(self) -> None:
        self._pool = ThreadedConnectionPool(
            1,
            max(2, PG_POOL_SIZE),
            host=PG_HOST,
            port=PG_PORT,
            user=PG_USER,
            password=PG_PASSWORD,
            dbname=PG_DATABASE,
            connect_timeout=10,
            keepalives=1,
            keepalives_idle=30,
            keepalives_interval=10,
            keepalives_count=3,
        )
        self._schema_lock = threading.Lock()
        self._ensure_schema()

    @contextmanager
    def _connection(self, *, vectors: bool = False):
        conn = self._pool.getconn()
        try:
            if conn.status != STATUS_READY:
                conn.rollback()
            if vectors:
                previous_autocommit = conn.autocommit
                conn.autocommit = True
                register_vector(conn)
                conn.autocommit = previous_autocommit
            yield conn
        finally:
            if conn.status != STATUS_READY:
                conn.rollback()
            self._pool.putconn(conn)

    def _ensure_schema(self) -> None:
        with self._schema_lock, self._connection() as conn:
            run_person_memory_migrations(conn)
        logger.info("人物长期记忆数据库结构已就绪")

    def start_conversation(
        self,
        *,
        conversation_id: str,
        device_id: str,
        person_id: str,
        person_name: str,
        privacy_epoch: int = 0,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> None:
        tenant_id = normalize_tenant_id(tenant_id)
        self._execute(
            """
            INSERT INTO person_conversations
                (conversation_id, tenant_id, device_id, person_id, person_name, privacy_epoch)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (conversation_id) DO UPDATE SET
                tenant_id = EXCLUDED.tenant_id,
                device_id = EXCLUDED.device_id,
                person_id = EXCLUDED.person_id,
                person_name = EXCLUDED.person_name,
                privacy_epoch = GREATEST(
                    person_conversations.privacy_epoch,
                    EXCLUDED.privacy_epoch
                ),
                updated_at = NOW()
            WHERE person_conversations.tenant_id = EXCLUDED.tenant_id
            """,
            (
                conversation_id,
                tenant_id,
                device_id,
                person_id,
                person_name,
                privacy_epoch,
            ),
        )

    def append_turn(
        self,
        *,
        conversation_id: str,
        person_id: str,
        user_text: str,
        assistant_text: str,
        attributed: bool,
        privacy_epoch: int = 0,
        privacy_reason: str = "",
        status: str = "completed",
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> str | None:
        tenant_id = normalize_tenant_id(tenant_id)
        user_text = (user_text or "").strip()[:8000]
        assistant_text = (assistant_text or "").strip()[:8000]
        if not user_text and not assistant_text:
            return None

        turn_id = str(uuid.uuid4())
        content_hash = hashlib.sha256(
            f"{conversation_id}\n{user_text}\n{assistant_text}".encode("utf-8")
        ).hexdigest()
        memory_eligible = bool(attributed and status == "completed" and user_text and assistant_text)

        with self._connection() as conn:
            try:
                conn.autocommit = False
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT conversation_id FROM person_conversations "
                        "WHERE conversation_id = %s AND tenant_id = %s FOR UPDATE",
                        (conversation_id, tenant_id),
                    )
                    if cur.fetchone() is None:
                        raise RuntimeError(f"person conversation not found: {conversation_id}")
                    cur.execute(
                        """
                        SELECT COALESCE(MAX(sequence_no), 0) + 1
                        FROM person_conversation_turns
                        WHERE conversation_id = %s
                        """,
                        (conversation_id,),
                    )
                    sequence_no = int(cur.fetchone()[0])
                    cur.execute(
                        """
                        INSERT INTO person_conversation_turns
                            (turn_id, conversation_id, person_id, sequence_no,
                             user_text, assistant_text, status, memory_eligible,
                             privacy_epoch, privacy_reason, content_hash)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            turn_id,
                            conversation_id,
                            person_id,
                            sequence_no,
                            user_text,
                            assistant_text,
                            status[:24],
                            memory_eligible,
                            max(0, int(privacy_epoch)),
                            (privacy_reason or "")[:80],
                            content_hash,
                        ),
                    )
                    for role, content in (("user", user_text), ("assistant", assistant_text)):
                        if content:
                            cur.execute(
                                """
                                INSERT INTO person_conversation_messages
                                    (conversation_id, person_id, role, content, attributed)
                                VALUES (%s, %s, %s, %s, %s)
                                """,
                                (conversation_id, person_id, role, content, attributed),
                            )
                    if memory_eligible and PERSON_MEMORY_IMPLICIT_EXTRACTION_ENABLED:
                        cur.execute(
                            """
                            INSERT INTO person_memory_jobs
                                (turn_id, person_id, conversation_id, available_at)
                            VALUES (
                                %s, %s, %s,
                                NOW() + (%s * INTERVAL '1 second')
                            )
                            ON CONFLICT (turn_id) DO NOTHING
                            """,
                            (
                                turn_id,
                                person_id,
                                conversation_id,
                                max(0.0, PERSON_MEMORY_DEBOUNCE_SECONDS),
                            ),
                        )
                    cur.execute(
                        """
                        UPDATE person_conversations
                        SET privacy_epoch = GREATEST(privacy_epoch, %s), updated_at = NOW()
                        WHERE conversation_id = %s
                        """,
                        (max(0, int(privacy_epoch)), conversation_id),
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        logger.info(
            "人物会话轮次事务已提交: conversation=%s turn=%s eligible=%s privacy_epoch=%d",
            conversation_id,
            turn_id,
            memory_eligible,
            privacy_epoch,
        )
        return turn_id

    def recent_context(self, person_id: str, *, limit: int = 6) -> list[dict]:
        if not person_id:
            return []
        with self._connection() as conn:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT role, content
                    FROM person_conversation_messages
                    WHERE person_id = %s AND attributed = TRUE
                    ORDER BY id DESC
                    LIMIT %s
                    """,
                    (person_id, max(2, min(100, int(limit)))),
                )
                rows: Sequence[tuple[str, str]] = cur.fetchall()
        return [{"role": role, "content": content} for role, content in reversed(rows)]

    def end_conversation(self, conversation_id: str, *, reason: str) -> None:
        self._execute(
            """
            UPDATE person_conversations
            SET ended_at = COALESCE(ended_at, NOW()), end_reason = %s, updated_at = NOW()
            WHERE conversation_id = %s
            """,
            ((reason or "")[:80], conversation_id),
        )

    def reassign_person_id(self, old_person_id: str, new_person_id: str) -> None:
        """Atomically migrate legacy name-hash memory to a stable employee UUID."""

        old_person_id = (old_person_id or "").strip()[:120]
        new_person_id = (new_person_id or "").strip()[:120]
        if not old_person_id or not new_person_id or old_person_id == new_person_id:
            return
        with self._connection() as conn:
            try:
                conn.autocommit = False
                with conn.cursor() as cur:
                    for table in (
                        "person_conversations",
                        "person_conversation_messages",
                        "person_conversation_turns",
                        "person_memory_jobs",
                        "person_memory_audit_logs",
                        "person_memory_daily_summaries",
                    ):
                        cur.execute(
                            f"UPDATE {table} SET person_id = %s WHERE person_id = %s",
                            (new_person_id, old_person_id),
                        )

                    cur.execute(
                        """
                        INSERT INTO person_memory_profiles (person_id, profile, version, updated_at)
                        SELECT %s, profile, version, updated_at
                        FROM person_memory_profiles
                        WHERE person_id = %s
                        ON CONFLICT (person_id) DO UPDATE SET
                            profile = EXCLUDED.profile || person_memory_profiles.profile,
                            version = GREATEST(
                                person_memory_profiles.version,
                                EXCLUDED.version
                            ) + 1,
                            updated_at = NOW()
                        """,
                        (new_person_id, old_person_id),
                    )
                    cur.execute(
                        "DELETE FROM person_memory_profiles WHERE person_id = %s",
                        (old_person_id,),
                    )

                    cur.execute(
                        """
                        SELECT old.fact_id, current.fact_id
                        FROM person_memory_facts AS old
                        JOIN person_memory_facts AS current
                          ON current.person_id = %s
                         AND current.normalized_key = old.normalized_key
                        WHERE old.person_id = %s
                        """,
                        (new_person_id, old_person_id),
                    )
                    for old_fact_id, current_fact_id in cur.fetchall():
                        cur.execute(
                            """
                            INSERT INTO person_memory_fact_sources (fact_id, turn_id)
                            SELECT %s, turn_id
                            FROM person_memory_fact_sources
                            WHERE fact_id = %s
                            ON CONFLICT DO NOTHING
                            """,
                            (current_fact_id, old_fact_id),
                        )
                        cur.execute(
                            "DELETE FROM person_memory_facts WHERE fact_id = %s",
                            (old_fact_id,),
                        )
                    cur.execute(
                        "UPDATE person_memory_facts SET person_id = %s WHERE person_id = %s",
                        (new_person_id, old_person_id),
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        logger.info(
            "历史人物记忆身份迁移完成: old=%s new=%s",
            old_person_id,
            new_person_id,
        )

    def claim_job_batch(
        self,
        worker_id: str,
        *,
        batch_size: int = PERSON_MEMORY_WORKER_BATCH_SIZE,
        lease_seconds: float = PERSON_MEMORY_WORKER_LEASE_SECONDS,
    ) -> MemoryJobBatch | None:
        with self._connection() as conn:
            try:
                conn.autocommit = False
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id, person_id, conversation_id
                        FROM person_memory_jobs
                        WHERE available_at <= NOW()
                          AND (
                              status = 'pending'
                              OR (status = 'running' AND lease_until < NOW())
                          )
                        ORDER BY id
                        LIMIT 1
                        FOR UPDATE SKIP LOCKED
                        """
                    )
                    first = cur.fetchone()
                    if first is None:
                        conn.commit()
                        return None
                    _, person_id, conversation_id = first
                    cur.execute(
                        """
                        SELECT id, turn_id, attempts
                        FROM person_memory_jobs
                        WHERE person_id = %s
                          AND conversation_id = %s
                          AND available_at <= NOW()
                          AND (
                              status = 'pending'
                              OR (status = 'running' AND lease_until < NOW())
                          )
                        ORDER BY id
                        LIMIT %s
                        FOR UPDATE SKIP LOCKED
                        """,
                        (person_id, conversation_id, max(1, int(batch_size))),
                    )
                    jobs = cur.fetchall()
                    job_ids = [int(row[0]) for row in jobs]
                    turn_ids = [str(row[1]) for row in jobs]
                    attempts = max(int(row[2]) for row in jobs) + 1
                    cur.execute(
                        """
                        UPDATE person_memory_jobs
                        SET status = 'running', attempts = attempts + 1,
                            lease_owner = %s,
                            lease_until = NOW() + (%s * INTERVAL '1 second'),
                            updated_at = NOW()
                        WHERE id = ANY(%s)
                        """,
                        (worker_id[:120], max(10.0, lease_seconds), job_ids),
                    )
                    cur.execute(
                        """
                        SELECT turn_id, sequence_no, user_text, assistant_text, created_at
                        FROM person_conversation_turns
                        WHERE turn_id = ANY(%s)
                        ORDER BY sequence_no
                        """,
                        (turn_ids,),
                    )
                    turns = tuple(
                        {
                            "turn_id": str(row[0]),
                            "sequence_no": int(row[1]),
                            "user_text": row[2],
                            "assistant_text": row[3],
                            "created_at": row[4].isoformat(),
                        }
                        for row in cur.fetchall()
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return MemoryJobBatch(tuple(job_ids), person_id, conversation_id, turns, attempts)

    def complete_jobs(self, job_ids: Sequence[int]) -> None:
        if not job_ids:
            return
        self._execute(
            """
            UPDATE person_memory_jobs
            SET status = 'done', lease_owner = '', lease_until = NULL,
                last_error = '', updated_at = NOW()
            WHERE id = ANY(%s)
            """,
            (list(job_ids),),
        )

    def fail_jobs(
        self,
        job_ids: Sequence[int],
        *,
        error: str,
        attempts: int,
        max_attempts: int,
    ) -> None:
        if not job_ids:
            return
        delay_seconds = min(900.0, 5.0 * (2 ** max(0, attempts - 1)))
        terminal = attempts >= max(1, max_attempts)
        self._execute(
            """
            UPDATE person_memory_jobs
            SET status = %s, lease_owner = '', lease_until = NULL,
                last_error = %s,
                available_at = NOW() + (%s * INTERVAL '1 second'),
                updated_at = NOW()
            WHERE id = ANY(%s)
            """,
            (
                "dead" if terminal else "pending",
                (error or "")[:4000],
                delay_seconds,
                list(job_ids),
            ),
        )

    def load_snapshot(self, person_id: str, *, fact_limit: int = 80) -> dict:
        with self._connection() as conn:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT profile, version FROM person_memory_profiles WHERE person_id = %s",
                    (person_id,),
                )
                profile_row = cur.fetchone()
                cur.execute(
                    """
                    SELECT fact_id, category, content, confidence, salience,
                           reinforcement_count, last_confirmed_at
                    FROM person_memory_facts
                    WHERE person_id = %s AND status = 'active'
                      AND (expires_at IS NULL OR expires_at > NOW())
                    ORDER BY confidence DESC, salience DESC, last_confirmed_at DESC
                    LIMIT %s
                    """,
                    (person_id, max(1, min(200, int(fact_limit)))),
                )
                facts = [
                    {
                        "fact_id": row[0],
                        "category": row[1],
                        "content": row[2],
                        "confidence": float(row[3]),
                        "salience": float(row[4]),
                        "reinforcement_count": int(row[5]),
                        "last_confirmed_at": row[6].isoformat(),
                    }
                    for row in cur.fetchall()
                ]
        return {
            "profile": dict(profile_row[0]) if profile_row else {},
            "profile_version": int(profile_row[1]) if profile_row else 0,
            "facts": facts,
        }

    def list_explicit_facts(self, person_id: str) -> tuple[dict, ...]:
        if not person_id:
            return ()
        with self._connection() as conn:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT fact_id, category, content, confidence, salience,
                           reinforcement_count, last_confirmed_at
                    FROM person_memory_facts
                    WHERE person_id = %s
                      AND status = 'active'
                      AND extractor_version = %s
                      AND (expires_at IS NULL OR expires_at > NOW())
                    ORDER BY last_confirmed_at ASC, fact_id ASC
                    """,
                    (person_id, EXPLICIT_MEMORY_EXTRACTOR_VERSION),
                )
                rows = cur.fetchall()
        return tuple(
            {
                "fact_id": row[0],
                "category": row[1],
                "content": row[2],
                "confidence": float(row[3]),
                "salience": float(row[4]),
                "reinforcement_count": int(row[5]),
                "last_confirmed_at": row[6].isoformat(),
                "explicit": True,
            }
            for row in rows
        )

    def apply_extraction(
        self,
        *,
        person_id: str,
        conversation_id: str,
        profile_updates: dict[str, str],
        facts_with_embeddings: Sequence[tuple[MemoryFactCandidate, list[float] | None]],
        retract_fact_ids: Sequence[str],
        extractor_version: str,
    ) -> dict:
        created = 0
        reinforced = 0
        retracted = 0
        with self._connection(vectors=True) as conn:
            try:
                conn.autocommit = False
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO person_memory_profiles (person_id)
                        VALUES (%s)
                        ON CONFLICT (person_id) DO NOTHING
                        """,
                        (person_id,),
                    )
                    cur.execute(
                        "SELECT profile, version FROM person_memory_profiles WHERE person_id = %s FOR UPDATE",
                        (person_id,),
                    )
                    current_profile, version = cur.fetchone()
                    merged_profile = dict(current_profile or {})
                    merged_profile.update(profile_updates)
                    cur.execute(
                        """
                        UPDATE person_memory_profiles
                        SET profile = %s, version = %s, updated_at = NOW()
                        WHERE person_id = %s AND version = %s
                        """,
                        (Json(merged_profile), int(version) + 1, person_id, int(version)),
                    )
                    if cur.rowcount != 1:
                        raise RuntimeError("person memory profile version conflict")

                    if retract_fact_ids:
                        cur.execute(
                            """
                            UPDATE person_memory_facts
                            SET status = 'retracted', last_confirmed_at = NOW()
                            WHERE person_id = %s AND fact_id = ANY(%s) AND status = 'active'
                            """,
                            (person_id, list(retract_fact_ids)),
                        )
                        retracted = cur.rowcount

                    for candidate, embedding in facts_with_embeddings:
                        fact_key = normalized_fact_key(candidate.content)
                        fact_id = str(uuid.uuid4())
                        cur.execute(
                            """
                            INSERT INTO person_memory_facts
                                (fact_id, person_id, category, content, normalized_key,
                                 tokens, confidence, salience, source_conversation_id,
                                 extractor_version, embedding_model, embedding)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (person_id, normalized_key) DO UPDATE SET
                                category = EXCLUDED.category,
                                content = EXCLUDED.content,
                                tokens = EXCLUDED.tokens,
                                confidence = GREATEST(
                                    person_memory_facts.confidence,
                                    EXCLUDED.confidence
                                ),
                                salience = GREATEST(
                                    person_memory_facts.salience,
                                    EXCLUDED.salience
                                ),
                                reinforcement_count = person_memory_facts.reinforcement_count + 1,
                                status = 'active',
                                source_conversation_id = EXCLUDED.source_conversation_id,
                                extractor_version = EXCLUDED.extractor_version,
                                embedding_model = CASE
                                    WHEN EXCLUDED.embedding IS NULL
                                    THEN person_memory_facts.embedding_model
                                    ELSE EXCLUDED.embedding_model
                                END,
                                embedding = COALESCE(
                                    EXCLUDED.embedding,
                                    person_memory_facts.embedding
                                ),
                                last_confirmed_at = NOW()
                            RETURNING fact_id, (xmax = 0) AS inserted
                            """,
                            (
                                fact_id,
                                person_id,
                                candidate.category,
                                candidate.content,
                                fact_key,
                                " ".join(tokenize(candidate.content)),
                                candidate.confidence,
                                candidate.salience,
                                conversation_id,
                                extractor_version[:80],
                                PERSON_MEMORY_EMBEDDING_MODEL[:160] if embedding else "",
                                embedding,
                            ),
                        )
                        stored_fact_id, inserted = cur.fetchone()
                        created += int(bool(inserted))
                        reinforced += int(not inserted)
                        for turn_id in candidate.source_turn_ids:
                            cur.execute(
                                """
                                INSERT INTO person_memory_fact_sources (fact_id, turn_id)
                                SELECT %s, turn_id
                                FROM person_conversation_turns
                                WHERE turn_id = %s AND person_id = %s
                                ON CONFLICT DO NOTHING
                                """,
                                (stored_fact_id, turn_id, person_id),
                            )

                    cur.execute(
                        """
                        SELECT COUNT(*)
                        FROM person_memory_facts
                        WHERE person_id = %s AND status = 'active'
                        """,
                        (person_id,),
                    )
                    active_facts = int(cur.fetchone()[0] or 0)
                    cur.execute(
                        """
                        INSERT INTO person_memory_audit_logs
                            (person_id, action, actor, conversation_id, detail)
                        VALUES (%s, 'extract', 'memory-worker', %s, %s)
                        """,
                        (
                            person_id,
                            conversation_id,
                            Json(
                                {
                                    "created": created,
                                    "reinforced": reinforced,
                                    "retracted": retracted,
                                    "active_facts": active_facts,
                                    "profile_sections": sorted(profile_updates),
                                    "extractor_version": extractor_version,
                                }
                            ),
                        ),
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return {
            "created": created,
            "reinforced": reinforced,
            "retracted": retracted,
            "profile_sections": len(profile_updates),
        }

    def retrieve_memory(
        self,
        person_id: str,
        *,
        query: str,
        query_embedding: list[float] | None,
        top_k: int,
    ) -> RetrievedPersonMemory:
        query_tokens = " ".join(tokenize(query))
        with self._connection(vectors=bool(query_embedding)) as conn:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT profile FROM person_memory_profiles WHERE person_id = %s",
                    (person_id,),
                )
                profile_row = cur.fetchone()
                if query_embedding:
                    cur.execute(
                        """
                        SELECT fact_id, category, content, confidence, salience,
                               reinforcement_count,
                               (1 - (embedding <=> %s::vector)) AS semantic_score,
                               CASE WHEN %s = '' THEN 0 ELSE
                                   ts_rank_cd(
                                       to_tsvector('simple', tokens),
                                       plainto_tsquery('simple', %s)
                                   )
                               END AS lexical_score
                        FROM person_memory_facts
                        WHERE person_id = %s AND status = 'active'
                          AND extractor_version <> %s
                          AND (expires_at IS NULL OR expires_at > NOW())
                        ORDER BY (
                            COALESCE(1 - (embedding <=> %s::vector), 0) * 0.55
                            + LEAST(1.0, CASE WHEN %s = '' THEN 0 ELSE
                                ts_rank_cd(
                                    to_tsvector('simple', tokens),
                                    plainto_tsquery('simple', %s)
                                ) * 4
                              END) * 0.20
                            + confidence * 0.15
                            + salience * 0.05
                            + LEAST(1.0, reinforcement_count / 5.0) * 0.05
                        ) DESC, last_confirmed_at DESC
                        LIMIT %s
                        """,
                        (
                            query_embedding,
                            query_tokens,
                            query_tokens,
                            person_id,
                            EXPLICIT_MEMORY_EXTRACTOR_VERSION,
                            query_embedding,
                            query_tokens,
                            query_tokens,
                            max(1, min(20, int(top_k))),
                        ),
                    )
                else:
                    cur.execute(
                        """
                        SELECT fact_id, category, content, confidence, salience,
                               reinforcement_count, 0.0, 0.0
                        FROM person_memory_facts
                        WHERE person_id = %s AND status = 'active'
                          AND extractor_version <> %s
                          AND (expires_at IS NULL OR expires_at > NOW())
                        ORDER BY confidence DESC, salience DESC, last_confirmed_at DESC
                        LIMIT %s
                        """,
                        (
                            person_id,
                            EXPLICIT_MEMORY_EXTRACTOR_VERSION,
                            max(1, min(20, int(top_k))),
                        ),
                    )
                facts = tuple(
                    {
                        "fact_id": row[0],
                        "category": row[1],
                        "content": row[2],
                        "confidence": float(row[3]),
                        "salience": float(row[4]),
                        "reinforcement_count": int(row[5]),
                        "semantic_score": float(row[6] or 0.0),
                        "lexical_score": float(row[7] or 0.0),
                    }
                    for row in cur.fetchall()
                )
        return RetrievedPersonMemory(
            person_id=person_id,
            profile=dict(profile_row[0]) if profile_row else {},
            facts=facts,
        )

    def retrieve_daily_summaries(
        self,
        person_id: str,
        *,
        query: str,
        query_embedding: list[float] | None,
        top_k: int = PERSON_MEMORY_DAILY_SUMMARY_TOP_K,
    ) -> tuple[dict, ...]:
        query_tokens = " ".join(tokenize(query))
        top_k = max(1, min(20, int(top_k)))
        with self._connection(vectors=bool(query_embedding)) as conn:
            conn.autocommit = True
            with conn.cursor() as cur:
                if query_embedding:
                    cur.execute(
                        """
                        SELECT summary_id, summary_date, content, source_turn_count,
                               (1 - (embedding <=> %s::vector)) AS semantic_score,
                               CASE WHEN %s = '' THEN 0 ELSE
                                   ts_rank_cd(
                                       to_tsvector('simple', tokens),
                                       plainto_tsquery('simple', %s)
                                   )
                               END AS lexical_score
                        FROM person_memory_daily_summaries
                        WHERE person_id = %s AND status = 'active'
                        ORDER BY (
                            COALESCE(1 - (embedding <=> %s::vector), 0) * 0.70
                            + LEAST(1.0, CASE WHEN %s = '' THEN 0 ELSE
                                ts_rank_cd(
                                    to_tsvector('simple', tokens),
                                    plainto_tsquery('simple', %s)
                                ) * 4
                              END) * 0.20
                            + 0.10
                        ) DESC, summary_date DESC
                        LIMIT %s
                        """,
                        (
                            query_embedding,
                            query_tokens,
                            query_tokens,
                            person_id,
                            query_embedding,
                            query_tokens,
                            query_tokens,
                            top_k,
                        ),
                    )
                else:
                    cur.execute(
                        """
                        SELECT summary_id, summary_date, content, source_turn_count,
                               0.0, 0.0
                        FROM person_memory_daily_summaries
                        WHERE person_id = %s AND status = 'active'
                        ORDER BY summary_date DESC
                        LIMIT %s
                        """,
                        (person_id, top_k),
                    )
                rows = cur.fetchall()
        return tuple(
            {
                "summary_id": str(row[0]),
                "summary_date": row[1].isoformat(),
                "content": str(row[2] or ""),
                "source_turn_count": int(row[3] or 0),
                "semantic_score": float(row[4] or 0.0),
                "lexical_score": float(row[5] or 0.0),
            }
            for row in rows
        )

    def load_daily_summary(
        self,
        *,
        person_id: str,
        summary_date: str,
    ) -> dict | None:
        with self._connection() as conn:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT summary_id, summary_date, content, source_turn_count
                    FROM person_memory_daily_summaries
                    WHERE person_id = %s
                      AND summary_date = %s::date
                      AND status = 'active'
                    LIMIT 1
                    """,
                    (person_id, summary_date),
                )
                row = cur.fetchone()
        if not row:
            return None
        return {
            "summary_id": str(row[0]),
            "summary_date": row[1].isoformat(),
            "content": str(row[2] or ""),
            "source_turn_count": int(row[3] or 0),
        }

    def find_daily_summary_candidates(self, *, limit: int = 5) -> tuple[DailySummaryCandidate, ...]:
        with self._connection() as conn:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT t.person_id, c.tenant_id, t.created_at::date AS summary_date,
                           COUNT(*) AS turn_count
                    FROM person_conversation_turns AS t
                    JOIN person_conversations AS c
                      ON c.conversation_id = t.conversation_id
                    LEFT JOIN person_memory_daily_summaries AS s
                      ON s.person_id = t.person_id
                     AND s.summary_date = t.created_at::date
                    WHERE t.memory_eligible = TRUE
                      AND t.status = 'completed'
                      AND t.created_at::date < CURRENT_DATE
                      AND s.summary_id IS NULL
                    GROUP BY t.person_id, c.tenant_id, t.created_at::date
                    ORDER BY summary_date ASC, t.person_id ASC
                    LIMIT %s
                    """,
                    (max(1, min(50, int(limit))),),
                )
                rows = cur.fetchall()
        return tuple(
            DailySummaryCandidate(
                person_id=str(row[0]),
                tenant_id=normalize_tenant_id(str(row[1] or DEFAULT_TENANT_ID)),
                summary_date=row[2].isoformat(),
                turn_count=int(row[3] or 0),
            )
            for row in rows
        )

    def load_daily_summary_turns(
        self,
        *,
        person_id: str,
        summary_date: str,
    ) -> tuple[dict, ...]:
        with self._connection() as conn:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT turn_id, sequence_no, user_text, assistant_text, created_at
                    FROM person_conversation_turns
                    WHERE person_id = %s
                      AND memory_eligible = TRUE
                      AND status = 'completed'
                      AND created_at::date = %s::date
                    ORDER BY created_at ASC, sequence_no ASC
                    LIMIT %s
                    """,
                    (
                        person_id,
                        summary_date,
                        max(1, min(500, PERSON_MEMORY_DAILY_SUMMARY_MAX_TURNS)),
                    ),
                )
                rows = cur.fetchall()
        used_chars = 0
        turns = []
        for row in rows:
            user_text = str(row[2] or "")[:2000]
            assistant_text = str(row[3] or "")[:2000]
            used_chars += len(user_text) + len(assistant_text)
            if used_chars > PERSON_MEMORY_DAILY_SUMMARY_MAX_CHARS:
                break
            turns.append(
                {
                    "turn_id": str(row[0]),
                    "sequence_no": int(row[1]),
                    "user_text": user_text,
                    "assistant_text": assistant_text,
                    "created_at": row[4].isoformat(),
                }
            )
        return tuple(turns)

    def upsert_daily_summary(
        self,
        *,
        person_id: str,
        tenant_id: str,
        summary_date: str,
        content: str,
        source_turn_count: int,
        embedding: list[float] | None,
        summarizer_version: str,
    ) -> dict:
        tenant_id = normalize_tenant_id(tenant_id)
        content = " ".join((content or "").split())[:4000]
        if not content:
            raise ValueError("daily summary content is empty")
        summary_id = str(uuid.uuid4())
        with self._connection(vectors=bool(embedding)) as conn:
            try:
                conn.autocommit = False
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT MIN(created_at), MAX(created_at)
                        FROM person_conversation_turns
                        WHERE person_id = %s
                          AND memory_eligible = TRUE
                          AND status = 'completed'
                          AND created_at::date = %s::date
                        """,
                        (person_id, summary_date),
                    )
                    started_at, ended_at = cur.fetchone()
                    cur.execute(
                        """
                        INSERT INTO person_memory_daily_summaries
                            (summary_id, person_id, tenant_id, summary_date, content, tokens,
                             source_turn_count, source_started_at, source_ended_at,
                             summarizer_version, embedding_model, embedding)
                        VALUES (%s, %s, %s, %s::date, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (person_id, summary_date) DO UPDATE SET
                            tenant_id = EXCLUDED.tenant_id,
                            content = EXCLUDED.content,
                            tokens = EXCLUDED.tokens,
                            source_turn_count = EXCLUDED.source_turn_count,
                            source_started_at = EXCLUDED.source_started_at,
                            source_ended_at = EXCLUDED.source_ended_at,
                            status = 'active',
                            summarizer_version = EXCLUDED.summarizer_version,
                            embedding_model = CASE
                                WHEN EXCLUDED.embedding IS NULL
                                THEN person_memory_daily_summaries.embedding_model
                                ELSE EXCLUDED.embedding_model
                            END,
                            embedding = COALESCE(
                                EXCLUDED.embedding,
                                person_memory_daily_summaries.embedding
                            ),
                            updated_at = NOW()
                        RETURNING summary_id
                        """,
                        (
                            summary_id,
                            person_id,
                            tenant_id,
                            summary_date,
                            content,
                            " ".join(tokenize(content)),
                            max(0, int(source_turn_count)),
                            started_at,
                            ended_at,
                            summarizer_version[:80],
                            PERSON_MEMORY_EMBEDDING_MODEL[:160] if embedding else "",
                            embedding,
                        ),
                    )
                    stored_summary_id = str(cur.fetchone()[0])
                    cur.execute(
                        """
                        INSERT INTO person_memory_audit_logs
                            (person_id, action, actor, detail)
                        VALUES (%s, 'daily_summary_upsert', 'memory-worker', %s)
                        """,
                        (
                            person_id,
                            Json(
                                {
                                    "summary_id": stored_summary_id,
                                    "tenant_id": tenant_id,
                                    "summary_date": summary_date,
                                    "source_turn_count": int(source_turn_count),
                                    "summarizer_version": summarizer_version,
                                    "embedding": bool(embedding),
                                }
                            ),
                        ),
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return {
            "summaryId": stored_summary_id,
            "personId": person_id,
            "tenantId": tenant_id,
            "summaryDate": summary_date,
            "sourceTurnCount": int(source_turn_count),
            "embedding": bool(embedding),
        }

    def mark_daily_summary_skipped(
        self,
        *,
        person_id: str,
        tenant_id: str,
        summary_date: str,
        source_turn_count: int,
        reason: str,
        summarizer_version: str,
    ) -> dict:
        tenant_id = normalize_tenant_id(tenant_id)
        summary_id = str(uuid.uuid4())
        with self._connection() as conn:
            try:
                conn.autocommit = False
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO person_memory_daily_summaries
                            (summary_id, person_id, tenant_id, summary_date, content, tokens,
                             source_turn_count, status, summarizer_version)
                        VALUES (%s, %s, %s, %s::date, '', '', %s, 'empty', %s)
                        ON CONFLICT (person_id, summary_date) DO UPDATE SET
                            tenant_id = EXCLUDED.tenant_id,
                            content = '',
                            tokens = '',
                            source_turn_count = EXCLUDED.source_turn_count,
                            status = 'empty',
                            summarizer_version = EXCLUDED.summarizer_version,
                            updated_at = NOW()
                        RETURNING summary_id
                        """,
                        (
                            summary_id,
                            person_id,
                            tenant_id,
                            summary_date,
                            max(0, int(source_turn_count)),
                            summarizer_version[:80],
                        ),
                    )
                    stored_summary_id = str(cur.fetchone()[0])
                    cur.execute(
                        """
                        INSERT INTO person_memory_audit_logs
                            (person_id, action, actor, detail)
                        VALUES (%s, 'daily_summary_skip', 'memory-worker', %s)
                        """,
                        (
                            person_id,
                            Json(
                                {
                                    "summary_id": stored_summary_id,
                                    "tenant_id": tenant_id,
                                    "summary_date": summary_date,
                                    "source_turn_count": int(source_turn_count),
                                    "reason": reason[:200],
                                    "summarizer_version": summarizer_version,
                                }
                            ),
                        ),
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return {
            "summaryId": stored_summary_id,
            "personId": person_id,
            "tenantId": tenant_id,
            "summaryDate": summary_date,
            "sourceTurnCount": int(source_turn_count),
            "status": "empty",
        }

    def memory_status(self, tenant_id: str = DEFAULT_TENANT_ID) -> dict:
        tenant_id = normalize_tenant_id(tenant_id)
        tenant_pattern = f"tenant:{tenant_id}:%"
        legacy_default_clause = (
            "OR person_id NOT LIKE 'tenant:%'"
            if tenant_id == DEFAULT_TENANT_ID
            else ""
        )
        with self._connection() as conn:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        COUNT(*) FILTER (WHERE status = 'pending'),
                        COUNT(*) FILTER (WHERE status = 'running'),
                        COUNT(*) FILTER (WHERE status = 'dead'),
                        EXTRACT(EPOCH FROM (
                            NOW() - MIN(created_at) FILTER (WHERE status = 'pending')
                        ))
                    FROM person_memory_jobs
                    WHERE person_id LIKE %s
                    """
                    + legacy_default_clause,
                    (tenant_pattern,),
                )
                pending, running, dead, oldest = cur.fetchone()
        return {
            "pending": int(pending or 0),
            "running": int(running or 0),
            "dead": int(dead or 0),
            "oldestPendingSeconds": round(float(oldest or 0.0), 3),
        }

    def upsert_arrival_task(
        self,
        *,
        tenant_id: str,
        creator_person_id: str,
        creator_name: str,
        target_person_id: str,
        target_name: str,
        content: str,
        exact_text: bool,
        repeat: bool,
        actor: str,
    ) -> dict:
        tenant_id = normalize_tenant_id(tenant_id)
        creator_person_id = (creator_person_id or "").strip()
        target_person_id = (target_person_id or "").strip()
        content = " ".join((content or "").split())[:240]
        if not creator_person_id or not target_person_id:
            raise ValueError("arrival task requires creator and target person")
        if not content:
            raise ValueError("arrival task content is empty")
        task_id = str(uuid.uuid4())
        with self._connection() as conn:
            try:
                conn.autocommit = False
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE person_arrival_tasks
                        SET status = 'replaced', updated_at = NOW()
                        WHERE tenant_id = %s
                          AND creator_person_id = %s
                          AND target_person_id = %s
                          AND action_type = 'say'
                          AND status = 'active'
                        """,
                        (tenant_id, creator_person_id, target_person_id),
                    )
                    replaced = cur.rowcount
                    cur.execute(
                        """
                        INSERT INTO person_arrival_tasks
                            (task_id, tenant_id, creator_person_id, creator_name,
                             target_person_id, target_name, action_type, content,
                             exact_text, repeat, status)
                        VALUES (%s, %s, %s, %s, %s, %s, 'say', %s, %s, %s, 'active')
                        """,
                        (
                            task_id,
                            tenant_id,
                            creator_person_id,
                            (creator_name or "")[:80],
                            target_person_id,
                            (target_name or "")[:80],
                            content,
                            bool(exact_text),
                            bool(repeat),
                        ),
                    )
                    cur.execute(
                        """
                        INSERT INTO person_memory_audit_logs
                            (person_id, action, actor, detail)
                        VALUES (%s, 'arrival_task_upsert', %s, %s)
                        """,
                        (
                            creator_person_id,
                            actor[:120],
                            Json(
                                {
                                    "task_id": task_id,
                                    "tenant_id": tenant_id,
                                    "target_person_id": target_person_id,
                                    "target_name": target_name,
                                    "content": content,
                                    "exact_text": bool(exact_text),
                                    "repeat": bool(repeat),
                                    "replaced": int(replaced),
                                }
                            ),
                        ),
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return {
            "taskId": task_id,
            "tenantId": tenant_id,
            "creatorPersonId": creator_person_id,
            "creatorName": creator_name,
            "targetPersonId": target_person_id,
            "targetName": target_name,
            "content": content,
            "exactText": bool(exact_text),
            "repeat": bool(repeat),
            "replaced": int(replaced),
        }

    def claim_arrival_tasks(
        self,
        *,
        tenant_id: str,
        target_person_id: str,
        cooldown_seconds: float = 0.0,
        limit: int = 5,
    ) -> list[dict]:
        tenant_id = normalize_tenant_id(tenant_id)
        target_person_id = (target_person_id or "").strip()
        if not target_person_id:
            return []
        cooldown_seconds = max(0.0, float(cooldown_seconds or 0.0))
        limit = max(1, min(int(limit), 20))
        with self._connection() as conn:
            try:
                conn.autocommit = False
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT task_id, creator_person_id, creator_name, target_person_id, target_name,
                               content, exact_text, repeat, trigger_count
                        FROM person_arrival_tasks
                        WHERE tenant_id = %s
                          AND target_person_id = %s
                          AND action_type = 'say'
                          AND status = 'active'
                          AND (
                              last_triggered_at IS NULL
                              OR last_triggered_at <= NOW() - (%s * INTERVAL '1 second')
                          )
                        ORDER BY updated_at DESC
                        LIMIT %s
                        FOR UPDATE SKIP LOCKED
                        """,
                        (tenant_id, target_person_id, cooldown_seconds, limit),
                    )
                    rows = cur.fetchall()
                    task_ids = [str(row[0]) for row in rows]
                    if task_ids:
                        cur.execute(
                            """
                            UPDATE person_arrival_tasks
                            SET trigger_count = trigger_count + 1,
                                last_triggered_at = NOW(),
                                status = CASE WHEN repeat THEN status ELSE 'done' END,
                                updated_at = NOW()
                            WHERE task_id = ANY(%s)
                            """,
                            (task_ids,),
                        )
                    tasks = [
                        {
                            "taskId": str(row[0]),
                            "creatorPersonId": str(row[1]),
                            "creatorName": str(row[2] or ""),
                            "targetPersonId": str(row[3] or ""),
                            "targetName": str(row[4] or ""),
                            "content": str(row[5] or ""),
                            "exactText": bool(row[6]),
                            "repeat": bool(row[7]),
                            "triggerCount": int(row[8] or 0),
                        }
                        for row in rows
                    ]
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return tasks

    def has_active_arrival_task(
        self,
        *,
        tenant_id: str,
        target_person_id: str,
    ) -> bool:
        tenant_id = normalize_tenant_id(tenant_id)
        target_person_id = (target_person_id or "").strip()
        if not target_person_id:
            return False
        with self._connection() as conn:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1
                    FROM person_arrival_tasks
                    WHERE tenant_id = %s
                      AND target_person_id = %s
                      AND action_type = 'say'
                      AND status = 'active'
                    LIMIT 1
                    """,
                    (tenant_id, target_person_id),
                )
                return cur.fetchone() is not None

    def cancel_arrival_tasks(
        self,
        *,
        tenant_id: str,
        creator_person_id: str,
        target_person_id: str = "",
        latest_only: bool = False,
        actor: str,
        reason: str,
    ) -> int:
        tenant_id = normalize_tenant_id(tenant_id)
        creator_person_id = (creator_person_id or "").strip()
        target_person_id = (target_person_id or "").strip()
        if not creator_person_id:
            return 0

        filters = [
            "tenant_id = %s",
            "creator_person_id = %s",
            "action_type = 'say'",
            "status = 'active'",
        ]
        params: list[object] = [tenant_id, creator_person_id]
        if target_person_id:
            filters.append("target_person_id = %s")
            params.append(target_person_id)
        where_clause = " AND ".join(filters)
        limit_clause = "LIMIT 1" if latest_only else ""

        with self._connection() as conn:
            try:
                conn.autocommit = False
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        WITH selected AS (
                            SELECT task_id
                            FROM person_arrival_tasks
                            WHERE {where_clause}
                            ORDER BY updated_at DESC
                            {limit_clause}
                            FOR UPDATE SKIP LOCKED
                        )
                        UPDATE person_arrival_tasks AS task
                        SET status = 'cancelled', updated_at = NOW()
                        FROM selected
                        WHERE task.task_id = selected.task_id
                        RETURNING task.task_id
                        """,
                        tuple(params),
                    )
                    task_ids = [str(row[0]) for row in cur.fetchall()]
                    if task_ids:
                        cur.execute(
                            """
                            INSERT INTO person_memory_audit_logs
                                (person_id, action, actor, detail)
                            VALUES (%s, 'arrival_task_cancel', %s, %s)
                            """,
                            (
                                creator_person_id,
                                actor[:120],
                                Json(
                                    {
                                        "task_ids": task_ids,
                                        "tenant_id": tenant_id,
                                        "target_person_id": target_person_id,
                                        "latest_only": bool(latest_only),
                                        "reason": reason[:200],
                                    }
                                ),
                            ),
                        )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return len(task_ids)

    def retract_facts(
        self,
        person_id: str,
        fact_ids: Sequence[str],
        *,
        actor: str,
        reason: str,
    ) -> int:
        fact_ids = [str(item)[:36] for item in fact_ids if item]
        if not fact_ids:
            return 0
        with self._connection() as conn:
            try:
                conn.autocommit = False
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE person_memory_facts
                        SET status = 'retracted', last_confirmed_at = NOW()
                        WHERE person_id = %s AND fact_id = ANY(%s) AND status = 'active'
                        """,
                        (person_id, fact_ids),
                    )
                    count = cur.rowcount
                    cur.execute(
                        """
                        INSERT INTO person_memory_audit_logs
                            (person_id, action, actor, detail)
                        VALUES (%s, 'retract', %s, %s)
                        """,
                        (
                            person_id,
                            actor[:120],
                            Json({"fact_ids": fact_ids, "reason": reason[:200]}),
                        ),
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return count

    def clear_person_memory(self, person_id: str, *, actor: str, reason: str) -> dict:
        with self._connection() as conn:
            try:
                conn.autocommit = False
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE person_memory_facts
                        SET status = 'retracted', last_confirmed_at = NOW()
                        WHERE person_id = %s AND status = 'active'
                        """,
                        (person_id,),
                    )
                    facts = cur.rowcount
                    cur.execute(
                        """
                        INSERT INTO person_memory_profiles (person_id, profile, version)
                        VALUES (%s, '{}'::jsonb, 1)
                        ON CONFLICT (person_id) DO UPDATE SET
                            profile = '{}'::jsonb,
                            version = person_memory_profiles.version + 1,
                            updated_at = NOW()
                        """,
                        (person_id,),
                    )
                    cur.execute(
                        """
                        INSERT INTO person_memory_audit_logs
                            (person_id, action, actor, detail)
                        VALUES (%s, 'clear', %s, %s)
                        """,
                        (person_id, actor[:120], Json({"reason": reason[:200]})),
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return {"factsRetracted": facts, "profileCleared": True}

    def _execute(self, statement: str, params: tuple) -> None:
        with self._connection() as conn:
            try:
                conn.autocommit = True
                with conn.cursor() as cur:
                    cur.execute(statement, params)
            except Exception:
                logger.exception("人物记忆数据库操作失败")
                raise

    def close(self) -> None:
        self._pool.closeall()


_repository: PostgresPersonMemoryRepository | None = None
_repository_lock = threading.Lock()


def get_person_memory_repository() -> PostgresPersonMemoryRepository:
    global _repository
    if _repository is None:
        with _repository_lock:
            if _repository is None:
                _repository = PostgresPersonMemoryRepository()
    return _repository

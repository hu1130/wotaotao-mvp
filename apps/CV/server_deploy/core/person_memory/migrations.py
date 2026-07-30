"""Versioned PostgreSQL schema migrations for person memory."""

from __future__ import annotations

import logging

from config import PERSON_MEMORY_EMBEDDING_DIM

logger = logging.getLogger("uvicorn.error")


def _migration_statements() -> list[tuple[int, tuple[str, ...]]]:
    dimension = max(1, int(PERSON_MEMORY_EMBEDDING_DIM))
    return [
        (
            1,
            (
                "CREATE EXTENSION IF NOT EXISTS vector",
                """
                CREATE TABLE IF NOT EXISTS person_conversations (
                    conversation_id VARCHAR(120) PRIMARY KEY,
                    device_id VARCHAR(80) NOT NULL,
                    person_id VARCHAR(120) NOT NULL,
                    person_name VARCHAR(80) NOT NULL,
                    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    ended_at TIMESTAMPTZ,
                    end_reason VARCHAR(80) NOT NULL DEFAULT ''
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS person_conversation_messages (
                    id BIGSERIAL PRIMARY KEY,
                    conversation_id VARCHAR(120) NOT NULL
                        REFERENCES person_conversations(conversation_id) ON DELETE CASCADE,
                    person_id VARCHAR(120) NOT NULL,
                    role VARCHAR(20) NOT NULL CHECK (role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    attributed BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """,
                """
                CREATE INDEX IF NOT EXISTS idx_person_messages_person_created
                ON person_conversation_messages (person_id, id DESC)
                """,
                """
                ALTER TABLE person_conversations
                ADD COLUMN IF NOT EXISTS privacy_epoch BIGINT NOT NULL DEFAULT 0
                """,
                """
                ALTER TABLE person_conversations
                ADD COLUMN IF NOT EXISTS memory_eligible BOOLEAN NOT NULL DEFAULT TRUE
                """,
                """
                ALTER TABLE person_conversations
                ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                """,
                """
                CREATE TABLE IF NOT EXISTS person_conversation_turns (
                    turn_id VARCHAR(36) PRIMARY KEY,
                    conversation_id VARCHAR(120) NOT NULL
                        REFERENCES person_conversations(conversation_id) ON DELETE CASCADE,
                    person_id VARCHAR(120) NOT NULL,
                    sequence_no INTEGER NOT NULL,
                    user_text TEXT NOT NULL DEFAULT '',
                    assistant_text TEXT NOT NULL DEFAULT '',
                    status VARCHAR(24) NOT NULL DEFAULT 'completed',
                    memory_eligible BOOLEAN NOT NULL DEFAULT FALSE,
                    privacy_epoch BIGINT NOT NULL DEFAULT 0,
                    privacy_reason VARCHAR(80) NOT NULL DEFAULT '',
                    content_hash CHAR(64) NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE (conversation_id, sequence_no)
                )
                """,
                """
                CREATE INDEX IF NOT EXISTS idx_person_turns_person_created
                ON person_conversation_turns (person_id, created_at DESC)
                """,
                """
                CREATE TABLE IF NOT EXISTS person_memory_jobs (
                    id BIGSERIAL PRIMARY KEY,
                    turn_id VARCHAR(36) NOT NULL UNIQUE
                        REFERENCES person_conversation_turns(turn_id) ON DELETE CASCADE,
                    person_id VARCHAR(120) NOT NULL,
                    conversation_id VARCHAR(120) NOT NULL,
                    status VARCHAR(24) NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    available_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    lease_owner VARCHAR(120) NOT NULL DEFAULT '',
                    lease_until TIMESTAMPTZ,
                    last_error TEXT NOT NULL DEFAULT '',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """,
                """
                CREATE INDEX IF NOT EXISTS idx_person_memory_jobs_claim
                ON person_memory_jobs (status, available_at, id)
                """,
                """
                CREATE TABLE IF NOT EXISTS person_memory_profiles (
                    person_id VARCHAR(120) PRIMARY KEY,
                    profile JSONB NOT NULL DEFAULT '{}'::jsonb,
                    version BIGINT NOT NULL DEFAULT 0,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """,
                f"""
                CREATE TABLE IF NOT EXISTS person_memory_facts (
                    fact_id VARCHAR(36) PRIMARY KEY,
                    person_id VARCHAR(120) NOT NULL,
                    category VARCHAR(40) NOT NULL,
                    content TEXT NOT NULL,
                    normalized_key CHAR(64) NOT NULL,
                    tokens TEXT NOT NULL DEFAULT '',
                    confidence DOUBLE PRECISION NOT NULL,
                    salience DOUBLE PRECISION NOT NULL DEFAULT 0.5,
                    reinforcement_count INTEGER NOT NULL DEFAULT 1,
                    status VARCHAR(24) NOT NULL DEFAULT 'active',
                    source_conversation_id VARCHAR(120) NOT NULL DEFAULT '',
                    extractor_version VARCHAR(80) NOT NULL DEFAULT '',
                    embedding_model VARCHAR(160) NOT NULL DEFAULT '',
                    embedding vector({dimension}),
                    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    last_confirmed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    expires_at TIMESTAMPTZ,
                    UNIQUE (person_id, normalized_key)
                )
                """,
                """
                CREATE INDEX IF NOT EXISTS idx_person_memory_facts_person_status
                ON person_memory_facts (person_id, status, last_confirmed_at DESC)
                """,
                """
                CREATE INDEX IF NOT EXISTS idx_person_memory_facts_tokens
                ON person_memory_facts USING gin (to_tsvector('simple', tokens))
                """,
                """
                CREATE INDEX IF NOT EXISTS idx_person_memory_facts_embedding_hnsw
                ON person_memory_facts
                USING hnsw (embedding vector_cosine_ops)
                WITH (m = 16, ef_construction = 64)
                """,
                """
                CREATE TABLE IF NOT EXISTS person_memory_fact_sources (
                    fact_id VARCHAR(36) NOT NULL
                        REFERENCES person_memory_facts(fact_id) ON DELETE CASCADE,
                    turn_id VARCHAR(36) NOT NULL
                        REFERENCES person_conversation_turns(turn_id) ON DELETE CASCADE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (fact_id, turn_id)
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS person_memory_audit_logs (
                    id BIGSERIAL PRIMARY KEY,
                    person_id VARCHAR(120) NOT NULL,
                    action VARCHAR(40) NOT NULL,
                    actor VARCHAR(120) NOT NULL DEFAULT '',
                    conversation_id VARCHAR(120) NOT NULL DEFAULT '',
                    detail JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """,
                """
                CREATE INDEX IF NOT EXISTS idx_person_memory_audit_person_created
                ON person_memory_audit_logs (person_id, created_at DESC)
                """,
            ),
        ),
        (
            2,
            (
                """
                ALTER TABLE person_conversations
                ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(64) NOT NULL DEFAULT 'default'
                """,
                """
                CREATE INDEX IF NOT EXISTS idx_person_conversations_tenant_updated
                ON person_conversations (tenant_id, updated_at DESC)
                """,
            ),
        ),
        (
            3,
            (
                """
                CREATE TABLE IF NOT EXISTS person_arrival_tasks (
                    task_id VARCHAR(36) PRIMARY KEY,
                    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
                    creator_person_id VARCHAR(120) NOT NULL,
                    creator_name VARCHAR(80) NOT NULL DEFAULT '',
                    target_person_id VARCHAR(120) NOT NULL,
                    target_name VARCHAR(80) NOT NULL DEFAULT '',
                    action_type VARCHAR(32) NOT NULL DEFAULT 'say',
                    content TEXT NOT NULL,
                    exact_text BOOLEAN NOT NULL DEFAULT FALSE,
                    repeat BOOLEAN NOT NULL DEFAULT TRUE,
                    status VARCHAR(24) NOT NULL DEFAULT 'active',
                    trigger_count INTEGER NOT NULL DEFAULT 0,
                    last_triggered_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """,
                """
                CREATE INDEX IF NOT EXISTS idx_person_arrival_tasks_target
                ON person_arrival_tasks (tenant_id, target_person_id, status, updated_at DESC)
                """,
                """
                CREATE INDEX IF NOT EXISTS idx_person_arrival_tasks_creator
                ON person_arrival_tasks (tenant_id, creator_person_id, updated_at DESC)
                """,
            ),
        ),
        (
            4,
            (
                """
                UPDATE person_memory_facts
                SET status = 'active'
                WHERE status = 'superseded'
                """,
            ),
        ),
        (
            5,
            (
                f"""
                CREATE TABLE IF NOT EXISTS person_memory_daily_summaries (
                    summary_id VARCHAR(36) PRIMARY KEY,
                    person_id VARCHAR(120) NOT NULL,
                    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
                    summary_date DATE NOT NULL,
                    content TEXT NOT NULL,
                    tokens TEXT NOT NULL DEFAULT '',
                    source_turn_count INTEGER NOT NULL DEFAULT 0,
                    source_started_at TIMESTAMPTZ,
                    source_ended_at TIMESTAMPTZ,
                    status VARCHAR(24) NOT NULL DEFAULT 'active',
                    summarizer_version VARCHAR(80) NOT NULL DEFAULT '',
                    embedding_model VARCHAR(160) NOT NULL DEFAULT '',
                    embedding vector({dimension}),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE (person_id, summary_date)
                )
                """,
                """
                CREATE INDEX IF NOT EXISTS idx_person_daily_summaries_person_status
                ON person_memory_daily_summaries (person_id, status, summary_date DESC)
                """,
                """
                CREATE INDEX IF NOT EXISTS idx_person_daily_summaries_tenant_date
                ON person_memory_daily_summaries (tenant_id, summary_date DESC)
                """,
                """
                CREATE INDEX IF NOT EXISTS idx_person_daily_summaries_tokens
                ON person_memory_daily_summaries USING gin (to_tsvector('simple', tokens))
                """,
                """
                CREATE INDEX IF NOT EXISTS idx_person_daily_summaries_embedding_hnsw
                ON person_memory_daily_summaries
                USING hnsw (embedding vector_cosine_ops)
                WITH (m = 16, ef_construction = 64)
                """,
            ),
        ),
    ]


def run_person_memory_migrations(conn) -> None:
    """Apply pending migrations in a transaction on the supplied connection."""

    previous_autocommit = conn.autocommit
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS person_memory_schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cur.execute("SELECT version FROM person_memory_schema_migrations")
            applied = {int(row[0]) for row in cur.fetchall()}
            for version, statements in _migration_statements():
                if version in applied:
                    continue
                for statement in statements:
                    cur.execute(statement)
                cur.execute(
                    "INSERT INTO person_memory_schema_migrations (version) VALUES (%s)",
                    (version,),
                )
                logger.info("人物记忆数据库迁移完成: version=%d", version)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.autocommit = previous_autocommit

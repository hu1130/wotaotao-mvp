"""pgvector 人脸特征向量存储: 单独存 PostgreSQL, 不混入 MySQL 业务库"""

from __future__ import annotations

import logging
import shutil
import threading
from contextlib import contextmanager

import numpy as np
import psycopg2
from pgvector.psycopg2 import register_vector
from psycopg2 import sql
from psycopg2.pool import ThreadedConnectionPool

from config import (
    PG_HOST,
    PG_PORT,
    PG_USER,
    PG_PASSWORD,
    PG_DATABASE,
    PG_POOL_SIZE,
    MATCH_THRESHOLD,
    EMPLOYEES_DIR,
)
from core.employee_names import normalize_employee_name, tenant_employee_directory
from core.tenant import DEFAULT_TENANT_ID, normalize_tenant_id

logger = logging.getLogger(__name__)

TABLE_NAME = "face_embeddings"
EMBEDDING_DIM = 512
POOL_CONNECTION_RETRIES = 2
_vector_pool: ThreadedConnectionPool | None = None
_vector_pool_lock = threading.Lock()
_vector_schema_initialized = False


class VectorDB:
    """pgvector 人脸特征库: 存储 & 向量相似度搜索"""

    def __init__(self):
        global _vector_pool, _vector_schema_initialized
        if _vector_pool is None or not _vector_schema_initialized:
            with _vector_pool_lock:
                if _vector_pool is None:
                    conn = self._create_conn()
                    try:
                        self._ensure_db(conn)
                    finally:
                        conn.close()
                    _vector_pool = ThreadedConnectionPool(
                        1,
                        max(1, PG_POOL_SIZE),
                        **self._connect_kwargs(PG_DATABASE),
                    )
                self._pool = _vector_pool
                if not _vector_schema_initialized:
                    self._init_table()
                    _vector_schema_initialized = True
                    logger.info(
                        "pgvector 共享连接池已就绪: %s:%s/%s size=%d",
                        PG_HOST,
                        PG_PORT,
                        PG_DATABASE,
                        PG_POOL_SIZE,
                    )
        else:
            self._pool = _vector_pool

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
        conn = psycopg2.connect(**VectorDB._connect_kwargs(database))
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
                    raise psycopg2.OperationalError("pgvector connection is not usable")

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
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (PG_DATABASE,))
        if cur.fetchone() is None:
            cur.execute(
                sql.SQL("CREATE DATABASE {}").format(sql.Identifier(PG_DATABASE))
            )
        cur.close()

    def _init_table(self):
        with self._connection(register_pgvector=False) as conn:
            cur = conn.cursor()
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            register_vector(conn)
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
                    id              SERIAL PRIMARY KEY,
                    tenant_id       VARCHAR(64) NOT NULL DEFAULT 'default',
                    employee_name   VARCHAR(255) NOT NULL,
                    embedding       vector({EMBEDDING_DIM}),
                    angle           VARCHAR(10) NOT NULL,
                    photo_path      VARCHAR(500),
                    created_at      TIMESTAMP DEFAULT NOW()
                )
            """)
            cur.execute(
                f"ALTER TABLE {TABLE_NAME} ADD COLUMN IF NOT EXISTS "
                "tenant_id VARCHAR(64) NOT NULL DEFAULT 'default'"
            )
            cur.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_{TABLE_NAME}_name
                ON {TABLE_NAME} (employee_name)
            """)
            cur.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_{TABLE_NAME}_tenant_name
                ON {TABLE_NAME} (tenant_id, employee_name)
            """)
            cur.close()
        self._ensure_notify_trigger()
        logger.info("pgvector 就绪: %s:%s/%s", PG_HOST, PG_PORT, PG_DATABASE)

    def _ensure_notify_trigger(self) -> None:
        with self._connection(register_pgvector=False) as conn:
            cur = conn.cursor()
            cur.execute("""
                CREATE OR REPLACE FUNCTION public.notify_face_embeddings_change()
                RETURNS trigger AS $$
                DECLARE
                    changed_name text;
                BEGIN
                    changed_name := COALESCE(NEW.tenant_id, OLD.tenant_id)
                        || '|' || COALESCE(NEW.employee_name, OLD.employee_name);
                    PERFORM pg_notify('face_embeddings_changed', changed_name);
                    RETURN COALESCE(NEW, OLD);
                END;
                $$ LANGUAGE plpgsql
            """)
            cur.execute(f"""
                DROP TRIGGER IF EXISTS trg_face_embeddings_notify ON {TABLE_NAME}
            """)
            cur.execute(f"""
                CREATE TRIGGER trg_face_embeddings_notify
                    AFTER INSERT OR DELETE OR UPDATE ON {TABLE_NAME}
                    FOR EACH ROW
                    EXECUTE FUNCTION public.notify_face_embeddings_change()
            """)
            cur.close()
        logger.info("PostgreSQL 变更通知触发器已就绪")

    def _create_hnsw_index(self):
        with self._connection() as conn:
            cur = conn.cursor()
            try:
                cur.execute(f"""
                    CREATE INDEX IF NOT EXISTS idx_{TABLE_NAME}_embedding_hnsw
                    ON {TABLE_NAME}
                    USING hnsw (embedding vector_cosine_ops)
                """)
            except Exception:
                logger.warning("HNSW 索引创建失败, 可能是 pgvector 版本不支持")
            cur.close()

    def upsert_employee(
        self,
        name: str,
        embeddings: list[tuple[np.ndarray, str, str]],
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> None:
        tenant_id = normalize_tenant_id(tenant_id)
        name = normalize_employee_name(name)
        with self._connection() as conn:
            cur = conn.cursor()
            cur.execute(
                f"DELETE FROM {TABLE_NAME} WHERE tenant_id = %s AND employee_name = %s",
                (tenant_id, name),
            )
            for embedding, angle, photo_path in embeddings:
                cur.execute(
                    f"INSERT INTO {TABLE_NAME} "
                    "(tenant_id, employee_name, embedding, angle, photo_path) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (tenant_id, name, embedding.tolist(), angle, photo_path),
                )
            cur.close()
        logger.info(
            "pgvector 写入: tenant=%s name=%s vectors=%d",
            tenant_id,
            name,
            len(embeddings),
        )

    def search(
        self,
        embedding: np.ndarray,
        top_k: int = 5,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> list[tuple[str, float]]:
        tenant_id = normalize_tenant_id(tenant_id)
        with self._connection() as conn:
            cur = conn.cursor()
            cur.execute(
                f"SELECT employee_name, 1 - (embedding <=> %s::vector) AS similarity "
                f"FROM {TABLE_NAME} "
                "WHERE tenant_id = %s "
                "ORDER BY embedding <=> %s::vector "
                "LIMIT %s",
                (embedding.tolist(), tenant_id, embedding.tolist(), top_k),
            )
            rows = cur.fetchall()
            cur.close()
        return [(r[0], float(r[1])) for r in rows if float(r[1]) >= MATCH_THRESHOLD]

    @staticmethod
    def _to_normalized_array(embedding) -> np.ndarray:
        if isinstance(embedding, str):
            arr = np.fromstring(embedding.strip("[]"), sep=",", dtype=np.float32)
        elif isinstance(embedding, list):
            arr = np.array(embedding, dtype=np.float32)
        elif hasattr(embedding, "to_list"):
            arr = np.array(embedding.to_list(), dtype=np.float32)
        else:
            arr = np.array(embedding, dtype=np.float32)
        norm = np.linalg.norm(arr)
        if norm > 0:
            arr = arr / norm
        return arr

    def get_all_embeddings(
        self, tenant_id: str = DEFAULT_TENANT_ID
    ) -> list[tuple[str, np.ndarray]]:
        tenant_id = normalize_tenant_id(tenant_id)
        with self._connection() as conn:
            cur = conn.cursor()
            cur.execute(
                f"SELECT employee_name, embedding "
                f"FROM {TABLE_NAME} WHERE tenant_id = %s ORDER BY employee_name, id",
                (tenant_id,),
            )
            rows = cur.fetchall()
            cur.close()
        return [(name, self._to_normalized_array(emb)) for name, emb in rows]

    def get_employee_embeddings(
        self, name: str, tenant_id: str = DEFAULT_TENANT_ID
    ) -> list[tuple[str, np.ndarray]]:
        tenant_id = normalize_tenant_id(tenant_id)
        with self._connection() as conn:
            cur = conn.cursor()
            cur.execute(
                f"SELECT employee_name, embedding "
                f"FROM {TABLE_NAME} "
                "WHERE tenant_id = %s AND employee_name = %s ORDER BY id",
                (tenant_id, name),
            )
            rows = cur.fetchall()
            cur.close()
        return [(employee_name, self._to_normalized_array(emb)) for employee_name, emb in rows]

    def employee_vector_counts(
        self, tenant_id: str = DEFAULT_TENANT_ID
    ) -> dict[str, int]:
        tenant_id = normalize_tenant_id(tenant_id)
        with self._connection() as conn:
            cur = conn.cursor()
            cur.execute(
                f"SELECT employee_name, COUNT(*) "
                f"FROM {TABLE_NAME} WHERE tenant_id = %s "
                "GROUP BY employee_name ORDER BY employee_name",
                (tenant_id,),
            )
            rows = cur.fetchall()
            cur.close()
        return {str(name): int(count) for name, count in rows}

    def list_employees(self, tenant_id: str = DEFAULT_TENANT_ID) -> list[str]:
        tenant_id = normalize_tenant_id(tenant_id)
        with self._connection() as conn:
            cur = conn.cursor()
            cur.execute(
                f"SELECT DISTINCT employee_name FROM {TABLE_NAME} "
                "WHERE tenant_id = %s ORDER BY employee_name",
                (tenant_id,),
            )
            rows = cur.fetchall()
            cur.close()
        return [r[0] for r in rows]

    def delete_employee(
        self, name: str, tenant_id: str = DEFAULT_TENANT_ID
    ) -> None:
        tenant_id = normalize_tenant_id(tenant_id)
        name = normalize_employee_name(name)
        with self._connection() as conn:
            cur = conn.cursor()
            cur.execute(
                f"DELETE FROM {TABLE_NAME} WHERE tenant_id = %s AND employee_name = %s",
                (tenant_id, name),
            )
            cur.close()
        photo_dir = tenant_employee_directory(EMPLOYEES_DIR, tenant_id, name)
        if photo_dir.exists():
            shutil.rmtree(photo_dir, ignore_errors=True)

    def count_total_vectors(self, tenant_id: str = DEFAULT_TENANT_ID) -> int:
        tenant_id = normalize_tenant_id(tenant_id)
        with self._connection() as conn:
            cur = conn.cursor()
            cur.execute(
                f"SELECT COUNT(*) FROM {TABLE_NAME} WHERE tenant_id = %s",
                (tenant_id,),
            )
            count = cur.fetchone()[0]
            cur.close()
            return count

    def __len__(self) -> int:
        with self._connection() as conn:
            cur = conn.cursor()
            cur.execute(
                f"SELECT COUNT(DISTINCT employee_name) FROM {TABLE_NAME} "
                "WHERE tenant_id = %s",
                (DEFAULT_TENANT_ID,),
            )
            count = cur.fetchone()[0]
            cur.close()
            return count

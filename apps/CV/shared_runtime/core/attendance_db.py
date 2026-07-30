"""考勤数据库: MySQL 记录上下班打卡时间及工作时长"""

from __future__ import annotations

import logging
import queue
import threading
import json
from contextlib import contextmanager
from datetime import date, datetime

import pymysql
import config as app_config
from core.tenant import DEFAULT_TENANT_ID, normalize_tenant_id

from config import (
    MYSQL_HOST,
    MYSQL_PORT,
    MYSQL_USER,
    MYSQL_PASSWORD,
    MYSQL_DATABASE,
    MYSQL_CHARSET,
    MYSQL_POOL_SIZE,
)

logger = logging.getLogger(__name__)
MYSQL_POOL_ACQUIRE_TIMEOUT_SECONDS = float(
    getattr(app_config, "MYSQL_POOL_ACQUIRE_TIMEOUT_SECONDS", 3.0)
)
MYSQL_TIME_ZONE = str(getattr(app_config, "MYSQL_TIME_ZONE", "+08:00") or "+08:00")
_pool_registry: dict[str, "MySQLConnectionPool"] = {}
_pool_registry_lock = threading.Lock()
_initialized_databases: set[str] = set()
_database_init_lock = threading.Lock()


class MySQLConnectionPool:
    """Small lazy PyMySQL pool for shared app workers."""

    def __init__(self, database: str, max_size: int):
        self.database = database
        self.max_size = max(1, max_size)
        self._idle: queue.Queue[pymysql.connections.Connection] = queue.Queue(
            maxsize=self.max_size
        )
        self._slots = threading.BoundedSemaphore(self.max_size)

    def get(self) -> pymysql.connections.Connection:
        if not self._slots.acquire(timeout=max(0.1, MYSQL_POOL_ACQUIRE_TIMEOUT_SECONDS)):
            logger.error(
                "MySQL 连接池获取超时: database=%s max_size=%d timeout=%.1fs",
                self.database,
                self.max_size,
                MYSQL_POOL_ACQUIRE_TIMEOUT_SECONDS,
            )
            raise TimeoutError("MySQL connection pool exhausted")
        conn = None
        try:
            try:
                conn = self._idle.get_nowait()
            except queue.Empty:
                conn = AttendanceDB._create_conn(database=self.database)

            try:
                conn.ping(reconnect=True)
            except Exception:
                self._close_conn(conn)
                conn = AttendanceDB._create_conn(database=self.database)
            return conn
        except Exception:
            self._slots.release()
            raise

    def put(self, conn: pymysql.connections.Connection) -> None:
        try:
            if getattr(conn, "open", False):
                try:
                    self._idle.put_nowait(conn)
                    return
                except queue.Full:
                    logger.warning("MySQL 连接池空闲队列已满，关闭多余连接")
            self._close_conn(conn)
        finally:
            self._slots.release()

    @staticmethod
    def _close_conn(conn: pymysql.connections.Connection | None) -> None:
        if conn is None:
            return
        try:
            conn.close()
        except Exception:
            pass


class AttendanceDB:
    """MySQL 考勤数据库"""

    def __init__(self):
        self._pool = self._shared_pool(MYSQL_DATABASE)
        if MYSQL_DATABASE not in _initialized_databases:
            with _database_init_lock:
                if MYSQL_DATABASE not in _initialized_databases:
                    conn = self._create_conn()
                    try:
                        self._ensure_database(conn)
                    finally:
                        conn.close()
                    self._init_table()
                    _initialized_databases.add(MYSQL_DATABASE)
                    logger.info(
                        "MySQL 共享连接池已就绪: %s:%s/%s size=%d",
                        MYSQL_HOST,
                        MYSQL_PORT,
                        MYSQL_DATABASE,
                        MYSQL_POOL_SIZE,
                    )

    @staticmethod
    def _shared_pool(database: str) -> MySQLConnectionPool:
        pool = _pool_registry.get(database)
        if pool is not None:
            return pool
        with _pool_registry_lock:
            return _pool_registry.setdefault(
                database,
                MySQLConnectionPool(database, MYSQL_POOL_SIZE),
            )

    @staticmethod
    def _create_conn(database: str | None = None) -> pymysql.connections.Connection:
        kwargs = dict(
            host=MYSQL_HOST,
            port=MYSQL_PORT,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            charset=MYSQL_CHARSET,
            autocommit=True,
            cursorclass=pymysql.cursors.Cursor,
            init_command=f"SET time_zone = '{MYSQL_TIME_ZONE}'",
        )
        if database:
            kwargs["database"] = database
        return pymysql.connect(**kwargs)

    @contextmanager
    def _connection(self):
        conn = self._pool.get()
        try:
            yield conn
        finally:
            self._pool.put(conn)

    def _ensure_database(self, conn):
        cur = conn.cursor()
        cur.execute(
            "CREATE DATABASE IF NOT EXISTS `%s`"
            " DEFAULT CHARACTER SET utf8mb4"
            " DEFAULT COLLATE utf8mb4_unicode_ci" % MYSQL_DATABASE
        )
        cur.close()

    def _init_table(self):
        with self._connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS attendance (
                    id          INT AUTO_INCREMENT PRIMARY KEY,
                    tenant_id   VARCHAR(64) NOT NULL DEFAULT 'default',
                    name        VARCHAR(255) NOT NULL,
                    date        VARCHAR(10)  NOT NULL,
                    check_in    VARCHAR(8)   NOT NULL,
                    check_out   VARCHAR(8),
                    duration    INT
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
            cur.execute("SHOW COLUMNS FROM attendance LIKE 'tenant_id'")
            if cur.fetchone() is None:
                cur.execute(
                    "ALTER TABLE attendance ADD COLUMN tenant_id VARCHAR(64) "
                    "NOT NULL DEFAULT 'default' AFTER id"
                )
            self._ensure_index(
                cur,
                "idx_attendance_name_date",
                "CREATE INDEX idx_attendance_name_date ON attendance (name, date)",
            )
            self._ensure_index(
                cur,
                "idx_attendance_open_checkout",
                "CREATE INDEX idx_attendance_open_checkout "
                "ON attendance (name, date, check_out, id)",
            )
            self._ensure_index(
                cur,
                "idx_attendance_tenant_name_date",
                "CREATE INDEX idx_attendance_tenant_name_date "
                "ON attendance (tenant_id, name, date)",
            )
            self._ensure_index(
                cur,
                "idx_attendance_tenant_open_checkout",
                "CREATE INDEX idx_attendance_tenant_open_checkout "
                "ON attendance (tenant_id, date, check_out, id)",
            )
            self._ensure_employees_table(cur)
            self._ensure_hrms_sync_table(cur)
            cur.close()

    @staticmethod
    def _ensure_index(cur, index_name: str, create_sql: str) -> None:
        cur.execute("SHOW INDEX FROM attendance WHERE Key_name=%s", (index_name,))
        if cur.fetchone() is None:
            cur.execute(create_sql)

    def check_in(self, name: str, tenant_id: str = DEFAULT_TENANT_ID) -> int:
        tenant_id = normalize_tenant_id(tenant_id)
        today = date.today().isoformat()
        now = datetime.now().strftime("%H:%M:%S")
        with self._connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO attendance (tenant_id, name, date, check_in) "
                "VALUES (%s, %s, %s, %s)",
                (tenant_id, name, today, now),
            )
            last_id = cur.lastrowid
            cur.close()
            return last_id

    def check_out(self, name: str, tenant_id: str = DEFAULT_TENANT_ID) -> int | None:
        tenant_id = normalize_tenant_id(tenant_id)
        today = date.today().isoformat()
        with self._connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT id, check_in FROM attendance "
                "WHERE tenant_id=%s AND name=%s AND date=%s AND check_out IS NULL "
                "ORDER BY id DESC LIMIT 1",
                (tenant_id, name, today),
            )
            row = cur.fetchone()
            if row is None:
                cur.close()
                return None
            row_id, check_in_str = row
            now = datetime.now().strftime("%H:%M:%S")
            t_in = datetime.strptime(check_in_str, "%H:%M:%S")
            t_out = datetime.strptime(now, "%H:%M:%S")
            duration = int((t_out - t_in).total_seconds() / 60)
            cur.execute(
                "UPDATE attendance SET check_out=%s, duration=%s WHERE id=%s",
                (now, duration, row_id),
            )
            cur.close()
            return duration

    def get_attendance_record(self, row_id: int) -> dict | None:
        with self._connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT id, tenant_id, name, date, check_in, check_out, duration "
                "FROM attendance WHERE id=%s LIMIT 1",
                (row_id,),
            )
            row = cur.fetchone()
            cur.close()
        if row is None:
            return None
        return {
            "id": row[0],
            "tenant_id": row[1],
            "name": row[2],
            "date": row[3],
            "check_in": row[4],
            "check_out": row[5],
            "duration": row[6],
        }

    def get_latest_today_record(
        self, name: str, tenant_id: str = DEFAULT_TENANT_ID
    ) -> dict | None:
        tenant_id = normalize_tenant_id(tenant_id)
        today = date.today().isoformat()
        with self._connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT id, tenant_id, name, date, check_in, check_out, duration "
                "FROM attendance WHERE tenant_id=%s AND name=%s AND date=%s "
                "ORDER BY id DESC LIMIT 1",
                (tenant_id, name, today),
            )
            row = cur.fetchone()
            cur.close()
        if row is None:
            return None
        return {
            "id": row[0],
            "tenant_id": row[1],
            "name": row[2],
            "date": row[3],
            "check_in": row[4],
            "check_out": row[5],
            "duration": row[6],
        }

    def get_today_records(
        self, name: str, tenant_id: str = DEFAULT_TENANT_ID
    ) -> list[dict]:
        tenant_id = normalize_tenant_id(tenant_id)
        today = date.today().isoformat()
        with self._connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT id, check_in, check_out, duration "
                "FROM attendance WHERE tenant_id=%s AND name=%s AND date=%s ORDER BY id",
                (tenant_id, name, today),
            )
            rows = cur.fetchall()
            cur.close()
        return [
            {"id": r[0], "check_in": r[1], "check_out": r[2], "duration": r[3]}
            for r in rows
        ]

    def has_any_record(self, name: str, tenant_id: str = DEFAULT_TENANT_ID) -> bool:
        tenant_id = normalize_tenant_id(tenant_id)
        with self._connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT 1 FROM attendance WHERE tenant_id=%s AND name=%s LIMIT 1",
                (tenant_id, name),
            )
            result = cur.fetchone() is not None
            cur.close()
            return result

    def has_record_today(self, name: str, tenant_id: str = DEFAULT_TENANT_ID) -> bool:
        return bool(self.get_today_records(name, tenant_id))

    def has_record_before_today(
        self, name: str, tenant_id: str = DEFAULT_TENANT_ID
    ) -> bool:
        tenant_id = normalize_tenant_id(tenant_id)
        today = date.today().isoformat()
        with self._connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT 1 FROM attendance "
                "WHERE tenant_id=%s AND name=%s AND date<%s LIMIT 1",
                (tenant_id, name, today),
            )
            result = cur.fetchone() is not None
            cur.close()
            return result

    def register_employee(self, name: str, tenant_id: str = DEFAULT_TENANT_ID) -> bool:
        tenant_id = normalize_tenant_id(tenant_id)
        with self._connection() as conn:
            cur = conn.cursor()
            self._ensure_employees_table(cur)
            cur.execute(
                "INSERT IGNORE INTO employees (tenant_id, name, employee_uuid) "
                "VALUES (%s, %s, UUID())",
                (tenant_id, name),
            )
            inserted = cur.rowcount > 0
            cur.close()
            return inserted

    def list_employees(self, tenant_id: str = DEFAULT_TENANT_ID) -> list[str]:
        tenant_id = normalize_tenant_id(tenant_id)
        with self._connection() as conn:
            cur = conn.cursor()
            self._ensure_employees_table(cur)
            cur.execute(
                "SELECT name FROM employees WHERE tenant_id=%s ORDER BY id",
                (tenant_id,),
            )
            names = [row[0] for row in cur.fetchall()]
            cur.close()
            return names

    def employee_exists(self, name: str, tenant_id: str = DEFAULT_TENANT_ID) -> bool:
        tenant_id = normalize_tenant_id(tenant_id)
        with self._connection() as conn:
            cur = conn.cursor()
            self._ensure_employees_table(cur)
            cur.execute(
                "SELECT 1 FROM employees WHERE tenant_id=%s AND name=%s LIMIT 1",
                (tenant_id, name),
            )
            exists = cur.fetchone() is not None
            cur.close()
            return exists

    def delete_employee(self, name: str, tenant_id: str = DEFAULT_TENANT_ID) -> bool:
        tenant_id = normalize_tenant_id(tenant_id)
        with self._connection() as conn:
            cur = conn.cursor()
            self._ensure_employees_table(cur)
            cur.execute(
                "DELETE FROM employees WHERE tenant_id=%s AND name=%s",
                (tenant_id, name),
            )
            deleted = cur.rowcount > 0
            cur.close()
            return deleted

    def batch_auto_checkout(self, tenant_id: str | None = None) -> list[dict]:
        """批量签退所有已签到但未签退的员工（18:00 后自动执行）。

        返回被签退的员工列表: [{name, row_id, check_in, duration}, ...]
        """
        today = date.today().isoformat()
        now_str = datetime.now().strftime("%H:%M:%S")
        t_out = datetime.strptime(now_str, "%H:%M:%S")
        checked_out: list[dict] = []

        with self._connection() as conn:
            cur = conn.cursor()
            if tenant_id is None:
                cur.execute(
                    "SELECT id, tenant_id, name, check_in FROM attendance "
                    "WHERE date=%s AND check_out IS NULL ORDER BY id",
                    (today,),
                )
            else:
                normalized_tenant = normalize_tenant_id(tenant_id)
                cur.execute(
                    "SELECT id, tenant_id, name, check_in FROM attendance "
                    "WHERE tenant_id=%s AND date=%s AND check_out IS NULL ORDER BY id",
                    (normalized_tenant, today),
                )
            rows = cur.fetchall()
            for row_id, row_tenant_id, name, check_in_str in rows:
                try:
                    t_in = datetime.strptime(check_in_str, "%H:%M:%S")
                    duration = int((t_out - t_in).total_seconds() / 60)
                except ValueError:
                    duration = 0
                cur.execute(
                    "UPDATE attendance SET check_out=%s, duration=%s WHERE id=%s",
                    (now_str, duration, row_id),
                )
                checked_out.append({
                    "tenant_id": row_tenant_id,
                    "name": name,
                    "row_id": row_id,
                    "check_in": check_in_str,
                    "check_out": now_str,
                    "duration": duration,
                })
            cur.close()
        return checked_out

    def enqueue_hrms_attendance_sync(
        self,
        *,
        tenant_id: str,
        attendance_row_id: int,
        action: str,
        payload: dict,
    ) -> int:
        tenant_id = normalize_tenant_id(tenant_id)
        payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        with self._connection() as conn:
            cur = conn.cursor()
            self._ensure_hrms_sync_table(cur)
            cur.execute(
                """
                INSERT INTO attendance_hrms_sync_outbox
                    (tenant_id, attendance_row_id, action, payload_json, status)
                VALUES (%s, %s, %s, %s, 'pending')
                ON DUPLICATE KEY UPDATE
                    payload_json=VALUES(payload_json),
                    status=IF(status='done', status, 'pending'),
                    updated_at=CURRENT_TIMESTAMP
                """,
                (tenant_id, attendance_row_id, action, payload_json),
            )
            cur.execute(
                "SELECT id FROM attendance_hrms_sync_outbox "
                "WHERE tenant_id=%s AND attendance_row_id=%s AND action=%s LIMIT 1",
                (tenant_id, attendance_row_id, action),
            )
            row = cur.fetchone()
            cur.close()
        return int(row[0]) if row else 0

    def list_pending_hrms_attendance_sync(self, limit: int = 50) -> list[dict]:
        limit = max(1, int(limit or 1))
        with self._connection() as conn:
            cur = conn.cursor()
            self._ensure_hrms_sync_table(cur)
            cur.execute(
                """
                SELECT id, tenant_id, attendance_row_id, action, payload_json, attempts
                FROM attendance_hrms_sync_outbox
                WHERE status='pending'
                  AND (next_attempt_at IS NULL OR next_attempt_at <= CURRENT_TIMESTAMP)
                ORDER BY id
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()
            cur.close()
        pending = []
        for row in rows:
            try:
                payload = json.loads(row[4] or "{}")
            except json.JSONDecodeError:
                payload = {}
            pending.append({
                "id": row[0],
                "tenant_id": row[1],
                "attendance_row_id": row[2],
                "action": row[3],
                "payload": payload,
                "attempts": row[5],
            })
        return pending

    def mark_hrms_attendance_sync_done(self, outbox_id: int) -> None:
        with self._connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE attendance_hrms_sync_outbox
                SET status='done', last_error='', updated_at=CURRENT_TIMESTAMP
                WHERE id=%s
                """,
                (outbox_id,),
            )
            cur.close()

    def mark_hrms_attendance_sync_failed(
        self, outbox_id: int, error: str, retry_seconds: float
    ) -> None:
        safe_error = str(error or "")[:1000]
        retry_seconds = max(1, int(retry_seconds or 1))
        with self._connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE attendance_hrms_sync_outbox
                SET attempts=attempts + 1,
                    last_error=%s,
                    next_attempt_at=DATE_ADD(CURRENT_TIMESTAMP, INTERVAL %s SECOND),
                    updated_at=CURRENT_TIMESTAMP
                WHERE id=%s
                """,
                (safe_error, retry_seconds, outbox_id),
            )
            cur.close()

    @staticmethod
    def _ensure_employees_table(cur) -> None:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS employees (
                id          INT AUTO_INCREMENT PRIMARY KEY,
                tenant_id   VARCHAR(64) NOT NULL DEFAULT 'default',
                name        VARCHAR(255) NOT NULL,
                employee_uuid CHAR(36) NOT NULL,
                created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uq_employees_tenant_name (tenant_id, name)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        cur.execute("SHOW COLUMNS FROM employees LIKE 'tenant_id'")
        if cur.fetchone() is None:
            cur.execute(
                "ALTER TABLE employees ADD COLUMN tenant_id VARCHAR(64) "
                "NOT NULL DEFAULT 'default' AFTER id"
            )
        cur.execute("SHOW COLUMNS FROM employees LIKE 'employee_uuid'")
        uuid_column = cur.fetchone()
        if uuid_column is None:
            cur.execute(
                "ALTER TABLE employees ADD COLUMN employee_uuid CHAR(36) NULL AFTER name"
            )
        if uuid_column is None or str(uuid_column[2]).upper() == "YES":
            cur.execute(
                "UPDATE employees SET employee_uuid = UUID() "
                "WHERE employee_uuid IS NULL OR employee_uuid = ''"
            )
            cur.execute("ALTER TABLE employees MODIFY employee_uuid CHAR(36) NOT NULL")
        cur.execute("SHOW INDEX FROM employees WHERE Key_name = 'uq_employees_uuid'")
        if cur.fetchone() is None:
            cur.execute(
                "ALTER TABLE employees ADD UNIQUE INDEX uq_employees_uuid (employee_uuid)"
            )
        cur.execute("SHOW INDEX FROM employees")
        index_columns: dict[str, list[str]] = {}
        unique_indexes: set[str] = set()
        for row in cur.fetchall():
            key_name = str(row[2])
            index_columns.setdefault(key_name, []).append(str(row[4]))
            if int(row[1]) == 0:
                unique_indexes.add(key_name)
        for key_name in unique_indexes:
            if key_name != "PRIMARY" and index_columns.get(key_name) == ["name"]:
                cur.execute(f"ALTER TABLE employees DROP INDEX `{key_name}`")
        cur.execute(
            "SHOW INDEX FROM employees WHERE Key_name = 'uq_employees_tenant_name'"
        )
        if cur.fetchone() is None:
            cur.execute(
                "ALTER TABLE employees ADD UNIQUE INDEX "
                "uq_employees_tenant_name (tenant_id, name)"
            )

    @staticmethod
    def _ensure_hrms_sync_table(cur) -> None:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS attendance_hrms_sync_outbox (
                id INT AUTO_INCREMENT PRIMARY KEY,
                tenant_id VARCHAR(64) NOT NULL,
                attendance_row_id INT NOT NULL,
                action VARCHAR(32) NOT NULL,
                payload_json MEDIUMTEXT NOT NULL,
                status VARCHAR(16) NOT NULL DEFAULT 'pending',
                attempts INT NOT NULL DEFAULT 0,
                last_error VARCHAR(1000) NOT NULL DEFAULT '',
                next_attempt_at DATETIME NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY uq_hrms_sync_attendance_action
                    (tenant_id, attendance_row_id, action),
                KEY idx_hrms_sync_pending (status, next_attempt_at, id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

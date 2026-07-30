"""Redis 连接池工厂: 统一管理所有 Redis 连接, 支持自动重连"""

import logging
import threading

import redis
from redis import ConnectionPool

from config import (
    REDIS_HOST,
    REDIS_PORT,
    REDIS_PASSWORD,
    REDIS_DB,
    REDIS_POOL_SIZE,
    REDIS_POOL_MAX_OVERFLOW,
)

logger = logging.getLogger(__name__)

_pool: ConnectionPool | None = None
_pool_lock = threading.Lock()


def _create_pool() -> ConnectionPool:
    return ConnectionPool(
        host=REDIS_HOST,
        port=REDIS_PORT,
        password=REDIS_PASSWORD or None,
        db=REDIS_DB,
        decode_responses=True,
        max_connections=max(1, REDIS_POOL_SIZE + REDIS_POOL_MAX_OVERFLOW),
        socket_connect_timeout=2,
        socket_timeout=2,
        socket_keepalive=True,
        health_check_interval=30,
        retry_on_timeout=True,
    )


def get_redis_pool() -> ConnectionPool:
    global _pool
    if _pool is not None:
        return _pool
    with _pool_lock:
        if _pool is None:
            _pool = _create_pool()
        return _pool


def reset_pool() -> None:
    """丢弃旧连接池并重建, 用于连接全部失效后的强制恢复"""
    global _pool
    with _pool_lock:
        if _pool is not None:
            try:
                _pool.disconnect()
            except Exception:
                pass
        _pool = _create_pool()
    logger.info("Redis 连接池已重建")


def get_redis_client() -> redis.Redis:
    return redis.Redis(connection_pool=get_redis_pool())


def ping_redis() -> bool:
    try:
        client = get_redis_client()
        client.ping()
        return True
    except Exception as exc:
        logger.warning("Redis 连接失败: %s", exc)
        return False


def try_reconnect() -> bool:
    """尝试重建连接池并 ping, 成功返回 True"""
    try:
        reset_pool()
        client = get_redis_client()
        client.ping()
        logger.info("Redis 重连成功")
        return True
    except Exception as exc:
        logger.debug("Redis 重连失败: %s", exc)
        return False

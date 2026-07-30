"""Redis 健康检查与重连: 统一管理所有模块的 Redis 连接状态"""

import logging
import time

logger = logging.getLogger(__name__)

DEFAULT_RECONNECT_INTERVAL = 15.0


class RedisHealthMonitor:
    """统一管理 Redis 健康检查与节流重连逻辑

    使用方式:
        health = RedisHealthMonitor(name="签到模块")
        health.initialize()
        ...
        if not health.ensure_connected():
            # 降级逻辑
            return
        health.client.set(...)
    """

    def __init__(
        self, name: str, reconnect_interval: float = DEFAULT_RECONNECT_INTERVAL
    ):
        self._name = name
        self._reconnect_interval = reconnect_interval
        self._client = None
        self._healthy: bool = False
        self._last_reconnect_attempt: float = 0.0

    def initialize(self) -> bool:
        try:
            from core.redis_client import get_redis_client

            self._client = get_redis_client()
            self._client.ping()
            self._healthy = True
            logger.info("%s: Redis 连接成功", self._name)
            return True
        except Exception as e:
            self._healthy = False
            logger.warning("%s: Redis 初始连接失败, 降级运行: %s", self._name, e)
            return False

    @property
    def is_healthy(self) -> bool:
        return self._healthy

    @property
    def client(self):
        return self._client

    def try_reconnect(self) -> bool:
        if self._healthy:
            return True
        now = time.time()
        if now - self._last_reconnect_attempt < self._reconnect_interval:
            return False
        self._last_reconnect_attempt = now
        try:
            from core.redis_client import try_reconnect as _do_reconnect

            if _do_reconnect():
                from core.redis_client import get_redis_client

                self._client = get_redis_client()
                self._healthy = True
                logger.info("%s: Redis 重连成功", self._name)
                return True
        except Exception:
            pass
        return False

    def mark_unhealthy(self) -> None:
        self._healthy = False

    def ensure_connected(self) -> bool:
        if self._healthy:
            return True
        return self.try_reconnect()

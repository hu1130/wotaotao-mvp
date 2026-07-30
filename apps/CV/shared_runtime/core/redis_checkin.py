"""Redis 签到去重: 当天签到状态 + 10 分钟冷却状态分开存储"""

import logging
import time

from config import CHECKIN_COOLDOWN_SECONDS
from core.redis_health import RedisHealthMonitor
from core.tenant import DEFAULT_TENANT_ID, normalize_tenant_id

logger = logging.getLogger(__name__)

KEY_PREFIX = "checkin"
COOLDOWN_PREFIX = "checkin_cooldown"
CHECKED_OUT_PREFIX = "checkout"


class RedisCheckIn:
    """Redis 签到去重"""

    def __init__(self, tenant_id: str = DEFAULT_TENANT_ID):
        self.tenant_id = normalize_tenant_id(tenant_id)
        self._health = RedisHealthMonitor(name="签到模块")
        self._health.initialize()
        self._local_date = self._today()
        self._local_checked_in: set[tuple[str, str]] = set()
        self._local_checked_out: set[tuple[str, str]] = set()
        self._local_cooldowns: dict[tuple[str, str], float] = {}

    @property
    def _r(self):
        return self._health.client

    def _on_redis_error(self, exc: Exception) -> None:
        self._health.mark_unhealthy()

    def _tenant(self, tenant_id: str | None) -> str:
        return normalize_tenant_id(tenant_id or self.tenant_id)

    def _today_key(self, name: str, tenant_id: str) -> str:
        return f"{KEY_PREFIX}:{tenant_id}:{self._today()}:{name}"

    def _checkout_key(self, name: str, tenant_id: str) -> str:
        return f"{CHECKED_OUT_PREFIX}:{tenant_id}:{self._today()}:{name}"

    def _cooldown_key(self, name: str, tenant_id: str) -> str:
        return f"{COOLDOWN_PREFIX}:{tenant_id}:{name}"

    def _today_set_key(self, tenant_id: str) -> str:
        return f"{KEY_PREFIX}:{tenant_id}:{self._today()}:set"

    def _legacy_today_key(self, name: str) -> str:
        return f"{KEY_PREFIX}:{self._today()}:{name}"

    def _legacy_checkout_key(self, name: str) -> str:
        return f"{CHECKED_OUT_PREFIX}:{self._today()}:{name}"

    def _legacy_cooldown_key(self, name: str) -> str:
        return f"{COOLDOWN_PREFIX}:{name}"

    def _legacy_today_set_key(self) -> str:
        return f"{KEY_PREFIX}:{self._today()}:set"

    def is_checked_in_today(self, name: str, tenant_id: str | None = None) -> bool:
        self._reset_local_if_new_day()
        tenant_id = self._tenant(tenant_id)
        local_key = (tenant_id, name)
        if local_key in self._local_checked_in:
            return True
        if not self._health.ensure_connected():
            return False
        try:
            exists = bool(self._r.exists(self._today_key(name, tenant_id)))
            if not exists and tenant_id == DEFAULT_TENANT_ID:
                exists = bool(self._r.exists(self._legacy_today_key(name)))
                if exists:
                    self._r.setex(
                        self._today_key(name, tenant_id),
                        self._seconds_until_tomorrow(),
                        "1",
                    )
            if exists:
                self._local_checked_in.add(local_key)
            return exists
        except Exception as exc:
            logger.warning(
                "Redis 今日签到状态读取失败, 使用本地兜底 (%s): %s", name, exc
            )
            self._on_redis_error(exc)
            return local_key in self._local_checked_in

    def is_checked_out_today(self, name: str, tenant_id: str | None = None) -> bool:
        self._reset_local_if_new_day()
        tenant_id = self._tenant(tenant_id)
        local_key = (tenant_id, name)
        if local_key in self._local_checked_out:
            return True
        if not self._health.ensure_connected():
            return False
        try:
            exists = bool(self._r.exists(self._checkout_key(name, tenant_id)))
            if not exists and tenant_id == DEFAULT_TENANT_ID:
                exists = bool(self._r.exists(self._legacy_checkout_key(name)))
                if exists:
                    self._r.setex(self._checkout_key(name, tenant_id), 86400, "1")
            if exists:
                self._local_checked_out.add(local_key)
            return exists
        except Exception as exc:
            logger.warning(
                "Redis 今日签退状态读取失败, 使用本地兜底 (%s): %s", name, exc
            )
            self._on_redis_error(exc)
            return local_key in self._local_checked_out

    def can_checkin(
        self,
        name: str,
        now: float | None = None,
        tenant_id: str | None = None,
    ) -> bool:
        self._reset_local_if_new_day()
        tenant_id = self._tenant(tenant_id)
        local_key = (tenant_id, name)
        now = time.time() if now is None else now
        if self._local_cooldowns.get(local_key, 0.0) > now:
            return False
        if not self._health.ensure_connected():
            return True
        try:
            ttl = self._r.ttl(self._cooldown_key(name, tenant_id))
            if ttl <= 0 and tenant_id == DEFAULT_TENANT_ID:
                ttl = self._r.ttl(self._legacy_cooldown_key(name))
            return ttl <= 0
        except Exception as exc:
            logger.warning("Redis 签到冷却读取失败, 使用本地兜底 (%s): %s", name, exc)
            self._on_redis_error(exc)
            return self._local_cooldowns.get(local_key, 0.0) <= now

    def mark_checked_in(self, name: str, tenant_id: str | None = None) -> None:
        self._reset_local_if_new_day()
        tenant_id = self._tenant(tenant_id)
        local_key = (tenant_id, name)
        self._local_checked_in.add(local_key)
        self._local_checked_out.discard(local_key)
        self._local_cooldowns[local_key] = time.time() + CHECKIN_COOLDOWN_SECONDS
        if not self._health.ensure_connected():
            return
        try:
            self._r.setex(
                self._today_key(name, tenant_id), self._seconds_until_tomorrow(), "1"
            )
            self._r.setex(
                self._cooldown_key(name, tenant_id), CHECKIN_COOLDOWN_SECONDS, "1"
            )
            self._r.sadd(self._today_set_key(tenant_id), name)
            self._r.expire(self._today_set_key(tenant_id), 86400)
        except Exception as exc:
            logger.warning("Redis 签到状态写入失败, 已保留本地兜底 (%s): %s", name, exc)
            self._on_redis_error(exc)

    def mark_checked_out(self, name: str, tenant_id: str | None = None) -> None:
        self._reset_local_if_new_day()
        tenant_id = self._tenant(tenant_id)
        self._local_checked_out.add((tenant_id, name))
        if not self._health.ensure_connected():
            return
        key = self._checkout_key(name, tenant_id)
        try:
            self._r.setex(key, 86400, "1")
        except Exception as exc:
            logger.warning("Redis 签退状态写入失败, 已保留本地兜底 (%s): %s", name, exc)
            self._on_redis_error(exc)

    def reset_checkin(self, name: str, tenant_id: str | None = None) -> None:
        self._reset_local_if_new_day()
        tenant_id = self._tenant(tenant_id)
        local_key = (tenant_id, name)
        self._local_checked_in.discard(local_key)
        self._local_cooldowns.pop(local_key, None)
        if not self._health.ensure_connected():
            self.mark_checked_out(name, tenant_id)
            return
        try:
            self._r.delete(self._today_key(name, tenant_id))
            self._r.delete(self._cooldown_key(name, tenant_id))
            self._r.srem(self._today_set_key(tenant_id), name)
            if tenant_id == DEFAULT_TENANT_ID:
                self._r.delete(self._legacy_today_key(name))
                self._r.delete(self._legacy_cooldown_key(name))
                self._r.srem(self._legacy_today_set_key(), name)
        except Exception as exc:
            logger.warning("Redis 签到状态清理失败, 已保留本地兜底 (%s): %s", name, exc)
            self._on_redis_error(exc)
        self.mark_checked_out(name, tenant_id)

    def get_today_count(self, tenant_id: str | None = None) -> int:
        self._reset_local_if_new_day()
        tenant_id = self._tenant(tenant_id)
        if not self._health.ensure_connected():
            return sum(1 for key in self._local_checked_in if key[0] == tenant_id)
        try:
            count = self._r.scard(self._today_set_key(tenant_id))
            if count == 0 and tenant_id == DEFAULT_TENANT_ID:
                count = self._r.scard(self._legacy_today_set_key())
            return count
        except Exception as exc:
            logger.warning("Redis 今日签到人数读取失败, 使用本地兜底: %s", exc)
            self._on_redis_error(exc)
            return sum(1 for key in self._local_checked_in if key[0] == tenant_id)

    @staticmethod
    def _today() -> str:
        from datetime import date

        return date.today().isoformat()

    def _reset_local_if_new_day(self) -> None:
        today = self._today()
        if self._local_date == today:
            return
        self._local_date = today
        self._local_checked_in.clear()
        self._local_checked_out.clear()
        self._local_cooldowns.clear()

    @staticmethod
    def _seconds_until_tomorrow() -> int:
        from datetime import datetime, timedelta

        now = datetime.now()
        tomorrow = (now + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        return max(1, int((tomorrow - now).total_seconds()))

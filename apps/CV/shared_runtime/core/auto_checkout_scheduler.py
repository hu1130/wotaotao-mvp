"""每日定时自动签退: 到达指定时间后批量签退所有已签到但未签退的员工。"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta

from config.common import get_int
from core.attendance_db import AttendanceDB
from core.events import EventBus
from core.hrms_attendance_sync import get_hrms_attendance_syncer
from core.redis_checkin import RedisCheckIn

logger = logging.getLogger(__name__)

# 默认 18:00 触发自动签退
AUTO_CHECKOUT_HOUR = get_int("AUTO_CHECKOUT_HOUR", 18)
AUTO_CHECKOUT_MINUTE = get_int("AUTO_CHECKOUT_MINUTE", 0)


class AutoCheckoutScheduler(threading.Thread):
    """每日自动签退调度器。

    到达 AUTO_CHECKOUT_HOUR:AUTO_CHECKOUT_MINUTE 后:
    1. 查询 MySQL 中所有今日未签退的签到记录
    2. 批量更新 check_out 和 duration
    3. 同步 Redis 签到/签退状态
    4. 发布 checkout 事件通知 avatar
    """

    def __init__(
        self,
        hour: int = AUTO_CHECKOUT_HOUR,
        minute: int = AUTO_CHECKOUT_MINUTE,
    ):
        super().__init__(name="AutoCheckoutScheduler", daemon=True)
        self.hour = hour
        self.minute = minute
        self._stop_event = threading.Event()
        self._attendance_db = AttendanceDB()
        self._checkin_store = RedisCheckIn()
        self._event_bus = EventBus()
        self._last_checkout_date: str | None = None

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        logger.info(
            "自动签退调度器已启动: 每日 %02d:%02d", self.hour, self.minute
        )
        while not self._stop_event.is_set():
            next_run = self._next_run_time()
            while not self._stop_event.is_set():
                wait_seconds = (next_run - datetime.now()).total_seconds()
                if wait_seconds <= 0:
                    break
                if self._stop_event.wait(min(2.0, wait_seconds)):
                    break
            if self._stop_event.is_set():
                break
            self._execute_auto_checkout()

    def _execute_auto_checkout(self) -> None:
        today = datetime.now().strftime("%Y-%m-%d")
        if self._last_checkout_date == today:
            logger.debug("今日自动签退已执行过，跳过")
            return

        try:
            results = self._attendance_db.batch_auto_checkout()
            if not results:
                logger.info("自动签退: 今日无未签退记录")
                self._last_checkout_date = today
                return

            for item in results:
                tenant_id = item["tenant_id"]
                name = item["name"]
                row_id = item["row_id"]
                duration = item["duration"]
                try:
                    self._checkin_store.reset_checkin(name, tenant_id)
                except Exception as exc:
                    logger.warning("自动签退 Redis 状态清理失败 (%s): %s", name, exc)
                try:
                    self._event_bus.checkout(
                        name, row_id, duration, tenant_id=tenant_id
                    )
                except Exception as exc:
                    logger.warning("自动签退事件发布失败 (%s): %s", name, exc)
                try:
                    get_hrms_attendance_syncer().enqueue_check_out(
                        self._attendance_db,
                        tenant_id=tenant_id,
                        name=name,
                        row_id=row_id,
                    )
                except Exception as exc:
                    logger.warning("自动签退 HRMS 同步入队失败 (%s): %s", name, exc)

            self._last_checkout_date = today
            logger.info(
                "自动签退完成: %d 人已签退 [%s]",
                len(results),
                ", ".join(r["name"] for r in results),
            )
        except Exception as exc:
            logger.error("自动签退执行异常: %s", exc)

    def _next_run_time(self) -> datetime:
        now = datetime.now()
        next_run = now.replace(
            hour=self.hour,
            minute=self.minute,
            second=0,
            microsecond=0,
        )
        if next_run <= now:
            next_run += timedelta(days=1)
        return next_run

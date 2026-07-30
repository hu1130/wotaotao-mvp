"""Attendance business-time policy shared by local and remote recognition."""

from __future__ import annotations

import os
from datetime import datetime, time as datetime_time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from config.common import get_int


ATTENDANCE_TIMEZONE = (
    os.getenv("ATTENDANCE_TIMEZONE")
    or os.getenv("BUSINESS_TIMEZONE")
    or "Asia/Shanghai"
).strip() or "Asia/Shanghai"


def _load_attendance_timezone():
    try:
        return ZoneInfo(ATTENDANCE_TIMEZONE)
    except ZoneInfoNotFoundError:
        if ATTENDANCE_TIMEZONE == "Asia/Shanghai":
            return timezone(timedelta(hours=8), name="Asia/Shanghai")
        raise


ATTENDANCE_TZ = _load_attendance_timezone()
CHECKOUT_AFTER_HOUR = get_int(
    "ATTENDANCE_CHECKOUT_AFTER_HOUR",
    get_int("AUTO_CHECKOUT_HOUR", 18),
)
CHECKOUT_AFTER_MINUTE = get_int(
    "ATTENDANCE_CHECKOUT_AFTER_MINUTE",
    get_int("AUTO_CHECKOUT_MINUTE", 0),
)


def attendance_timezone_name() -> str:
    return ATTENDANCE_TIMEZONE


def business_now() -> datetime:
    return datetime.now(ATTENDANCE_TZ)


def _as_business_time(now: datetime | None = None) -> datetime:
    if now is None:
        return business_now()
    if now.tzinfo is not None:
        return now.astimezone(ATTENDANCE_TZ)
    return now


def checkout_after_time() -> datetime_time:
    return datetime_time(
        hour=max(0, min(23, CHECKOUT_AFTER_HOUR)),
        minute=max(0, min(59, CHECKOUT_AFTER_MINUTE)),
    )


def is_checkout_window(now: datetime | None = None) -> bool:
    current = _as_business_time(now)
    return current.time() >= checkout_after_time()


def should_checkout_checked_in_presence(
    presence_state: Any,
    *,
    now_seconds: float,
    min_absent_seconds: float,
    now: datetime | None = None,
) -> bool:
    """Return true when a checked-in employee should sign out on recognition.

    Sign-out starts after the configured time and is tied to a recognition/re-entry
    event. A newly checked-in employee remains present, so the next continuous frame
    will not immediately sign them out.
    """

    if not is_checkout_window(now):
        return False
    if presence_state is None:
        return True
    if bool(getattr(presence_state, "present", False)):
        return False
    absent_since = float(getattr(presence_state, "absent_since", 0.0) or 0.0)
    if absent_since <= 0:
        return True
    return now_seconds - absent_since >= max(0.0, min_absent_seconds)

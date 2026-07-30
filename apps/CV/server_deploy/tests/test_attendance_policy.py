from __future__ import annotations

import unittest
from dataclasses import dataclass
from datetime import UTC, datetime

from core.attendance_policy import (
    is_checkout_window,
    should_checkout_checked_in_presence,
)


@dataclass
class PresenceState:
    present: bool = False
    absent_since: float = 0.0


class AttendancePolicyTests(unittest.TestCase):
    def test_checkout_window_starts_at_configured_time(self):
        self.assertFalse(is_checkout_window(datetime(2026, 7, 20, 17, 59, 59)))
        self.assertTrue(is_checkout_window(datetime(2026, 7, 20, 18, 0, 0)))

    def test_checkout_window_uses_business_timezone_for_aware_datetime(self):
        self.assertFalse(
            is_checkout_window(datetime(2026, 7, 20, 9, 59, 59, tzinfo=UTC))
        )
        self.assertTrue(
            is_checkout_window(datetime(2026, 7, 20, 10, 0, 0, tzinfo=UTC))
        )

    def test_after_hours_existing_checked_in_without_local_presence_can_checkout(self):
        self.assertTrue(
            should_checkout_checked_in_presence(
                None,
                now_seconds=100.0,
                min_absent_seconds=2.0,
                now=datetime(2026, 7, 20, 18, 1, 0),
            )
        )

    def test_after_hours_continuous_presence_does_not_checkout_immediately(self):
        self.assertFalse(
            should_checkout_checked_in_presence(
                PresenceState(present=True),
                now_seconds=100.0,
                min_absent_seconds=2.0,
                now=datetime(2026, 7, 20, 18, 1, 0),
            )
        )

    def test_after_hours_reentry_after_absence_can_checkout(self):
        self.assertTrue(
            should_checkout_checked_in_presence(
                PresenceState(present=False, absent_since=90.0),
                now_seconds=100.0,
                min_absent_seconds=2.0,
                now=datetime(2026, 7, 20, 18, 1, 0),
            )
        )

    def test_after_hours_brief_absence_does_not_checkout(self):
        self.assertFalse(
            should_checkout_checked_in_presence(
                PresenceState(present=False, absent_since=99.0),
                now_seconds=100.0,
                min_absent_seconds=2.0,
                now=datetime(2026, 7, 20, 18, 1, 0),
            )
        )


if __name__ == "__main__":
    unittest.main()

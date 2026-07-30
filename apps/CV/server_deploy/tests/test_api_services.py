from __future__ import annotations

import unittest
from unittest.mock import patch

from api.services import AttendanceService


class AttendanceServiceTests(unittest.TestCase):
    def test_today_records_does_not_initialize_redis_components(self):
        with (
            patch("api.services.AttendanceDB") as attendance_db,
            patch("api.services.RedisCheckIn") as redis_checkin,
            patch("api.services.EventBus") as event_bus,
        ):
            attendance_db.return_value.get_today_records.return_value = []

            result = AttendanceService("tenant-read-only").today_records("Alice")

        self.assertEqual(result["tenantId"], "tenant-read-only")
        self.assertEqual(result["records"], [])
        redis_checkin.assert_not_called()
        event_bus.assert_not_called()

    def test_check_in_initializes_tenant_scoped_redis_components_lazily(self):
        with (
            patch("api.services.AttendanceDB") as attendance_db,
            patch("api.services.RedisCheckIn") as redis_checkin,
            patch("api.services.EventBus") as event_bus,
        ):
            attendance_db.return_value.employee_exists.return_value = True
            attendance_db.return_value.check_in.return_value = 7
            redis_checkin.return_value.is_checked_in_today.return_value = False

            result = AttendanceService("tenant-write").check_in("Alice")

        self.assertTrue(result["checkedIn"])
        redis_checkin.assert_called_once_with("tenant-write")
        event_bus.assert_called_once_with(tenant_id="tenant-write")


if __name__ == "__main__":
    unittest.main()

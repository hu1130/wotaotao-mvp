from __future__ import annotations

import unittest

from core.remote_recognition import RemoteCheckInStore


class FakeAttendanceClient:
    def __init__(self):
        self.records: list[dict] = []

    def get(self, path: str, timeout: int = 3) -> dict:
        return {"data": {"records": list(self.records)}}


class RemoteCheckInStoreTests(unittest.TestCase):
    def test_local_checkout_cache_resets_on_new_day(self):
        current_date = "2026-07-20"
        client = FakeAttendanceClient()
        store = RemoteCheckInStore(
            client=client,
            today_provider=lambda: current_date,
        )

        store.update_from_frame({"today_count": 1, "checked_in_names": ["Alice"]})
        store.mark_checked_out("Alice")

        self.assertTrue(store.is_checked_out_today("Alice"))
        self.assertEqual(store.get_today_count(), 1)

        current_date = "2026-07-21"
        client.records = []

        self.assertFalse(store.is_checked_out_today("Alice"))
        self.assertFalse(store.is_checked_in_today("Alice"))
        self.assertEqual(store.get_today_count(), 0)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest
import threading
from unittest.mock import patch

import core.remote_recognition as module
from core.remote_recognition import (
    RemoteCheckedInPresence,
    RemoteRecognitionService,
    RemoteStrangerPresence,
)


class FakeArrivalTaskRepository:
    def __init__(self, *, active: bool):
        self.active = active
        self.claim_calls: list[dict] = []

    def has_active_arrival_task(self, **kwargs) -> bool:
        return self.active

    def claim_arrival_tasks(self, **kwargs) -> list[dict]:
        self.claim_calls.append(kwargs)
        if not self.active:
            return []
        return [
            {
                "taskId": "task-1",
                "creatorPersonId": "person-1",
                "creatorName": "小羊",
                "targetPersonId": "person-1",
                "targetName": "小羊",
                "content": "王总",
                "exactText": True,
                "repeat": True,
                "triggerCount": 0,
            }
        ]


class FakeDispatcher:
    def __init__(self) -> None:
        self.speeches: list[dict] = []

    def emit_custom_speech(self, **kwargs):
        self.speeches.append(kwargs)

        class Result:
            speech_sent = True

        return Result()


class FakeEventBus:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def publish(self, event_type: str, payload: dict) -> None:
        self.events.append((event_type, payload))


class FakeAttendanceDB:
    def __init__(self, duration: int | None = 42) -> None:
        self.duration = duration
        self.checkouts: list[tuple[str, str]] = []

    def check_out(self, name: str, tenant_id: str) -> int | None:
        self.checkouts.append((name, tenant_id))
        return self.duration


class FakeCheckinStore:
    def __init__(self) -> None:
        self.reset_calls: list[tuple[str, str]] = []

    def reset_checkin(self, name: str, tenant_id: str) -> None:
        self.reset_calls.append((name, tenant_id))


class ArrivalTaskRepeatPriorityTests(unittest.TestCase):
    def make_service(self) -> RemoteRecognitionService:
        service = RemoteRecognitionService.__new__(RemoteRecognitionService)
        service._checked_in_presence = {
            ("scope-1", "小羊"): RemoteCheckedInPresence(
                present=False,
                entered_at=60.0,
                last_seen_at=70.0,
                absent_since=70.0,
            )
        }
        service._last_repeat_feedback = {}
        service.avatar_dispatcher = FakeDispatcher()
        service.event_bus = FakeEventBus()
        service._stable_person_id = lambda name, tenant_id: "person-1"
        service._tenant_from_scope_key = lambda scope_key: "tenant-a"
        service._maybe_checked_in_stare_event = lambda *args, **kwargs: None
        service._emit_avatar_event = lambda event_type, payload: service.event_bus.publish(
            event_type, payload
        )
        return service

    def test_arrival_task_suppresses_repeat_on_repeat_reentry(self) -> None:
        service = self.make_service()
        repository = FakeArrivalTaskRepository(active=True)

        with patch.object(module, "get_person_memory_repository", return_value=repository):
            service._handle_checked_in_presence(
                "scope-1",
                "小羊",
                105.0,
                tenant_id="tenant-a",
            )

        self.assertEqual(len(repository.claim_calls), 1)
        self.assertEqual(len(service.avatar_dispatcher.speeches), 1)
        self.assertEqual(service.avatar_dispatcher.speeches[0]["event_type"], "arrival_task")
        self.assertNotIn(("repeat_checkin", {"name": "小羊"}), service.event_bus.events)
        self.assertFalse(any(event_type == "repeat" for event_type, _ in service.event_bus.events))

    def test_first_seen_checked_in_presence_triggers_repeat(self) -> None:
        service = self.make_service()
        service._checked_in_presence = {}
        repository = FakeArrivalTaskRepository(active=False)

        with patch.object(module, "get_person_memory_repository", return_value=repository):
            service._handle_checked_in_presence(
                "scope-1",
                "小羊",
                105.0,
                tenant_id="tenant-a",
            )

        event_types = [event_type for event_type, _ in service.event_bus.events]
        self.assertIn("repeat_checkin", event_types)
        self.assertIn("repeat", event_types)
        self.assertIn(("scope-1", "小羊"), service._checked_in_presence)

    def test_first_seen_recovered_track_does_not_trigger_repeat(self) -> None:
        service = self.make_service()
        service._checked_in_presence = {}
        repository = FakeArrivalTaskRepository(active=False)

        with patch.object(module, "get_person_memory_repository", return_value=repository):
            service._handle_checked_in_presence(
                "scope-1",
                "小羊",
                105.0,
                tenant_id="tenant-a",
                emit_repeat=False,
            )

        self.assertFalse(service.event_bus.events)
        self.assertIn(("scope-1", "小羊"), service._checked_in_presence)

    def test_checkout_due_suppresses_repeat_reentry(self) -> None:
        service = self.make_service()
        service.attendance_db = FakeAttendanceDB(duration=8)
        service.checkin_store = FakeCheckinStore()

        with patch.object(module, "should_checkout_checked_in_presence", return_value=True):
            result = service._checkout_checked_in_presence_if_due_locked(
                "scope-1",
                "小羊",
                105.0,
                tenant_id="tenant-a",
                source="test",
            )

        self.assertTrue(result["checkedOut"])
        self.assertEqual(result["durationMinutes"], 8)
        self.assertEqual(service.attendance_db.checkouts, [("小羊", "tenant-a")])
        self.assertEqual(service.checkin_store.reset_calls, [("小羊", "tenant-a")])
        self.assertNotIn(("scope-1", "小羊"), service._checked_in_presence)
        event_types = [event_type for event_type, _ in service.event_bus.events]
        self.assertIn("checkout", event_types)
        self.assertIn("check_out", event_types)
        self.assertNotIn("repeat_checkin", event_types)
        self.assertNotIn("repeat", event_types)

    def test_short_camera_dropout_does_not_trigger_repeat(self) -> None:
        service = self.make_service()
        service._checked_in_presence[("scope-1", "小羊")] = RemoteCheckedInPresence(
            present=False,
            entered_at=90.0,
            last_seen_at=100.0,
            absent_since=100.0,
        )
        repository = FakeArrivalTaskRepository(active=False)

        with patch.object(module, "get_person_memory_repository", return_value=repository):
            service._handle_checked_in_presence(
                "scope-1",
                "小羊",
                105.0,
                tenant_id="tenant-a",
            )

        self.assertFalse(repository.claim_calls)
        event_types = [event_type for event_type, _ in service.event_bus.events]
        self.assertNotIn("repeat_checkin", event_types)
        self.assertNotIn("repeat", event_types)


class ActiveStareTriggerTests(unittest.TestCase):
    def make_service(self) -> RemoteRecognitionService:
        service = RemoteRecognitionService.__new__(RemoteRecognitionService)
        service._lock = threading.RLock()
        service._checked_in_presence = {}
        service._stranger_presence = {}
        service._stranger_suppressed_until = {}
        service._last_stranger_suppress_log_at = {}
        service.event_bus = FakeEventBus()
        service._emit_avatar_event = lambda *args, **kwargs: None
        service._tenant_from_scope_key = lambda scope_key: "tenant-a"
        return service

    def event_count(self, service: RemoteRecognitionService, event_type: str) -> int:
        return sum(1 for current, _ in service.event_bus.events if current == event_type)

    def test_checked_in_stare_triggers_once_per_presence(self) -> None:
        service = self.make_service()
        state = RemoteCheckedInPresence(
            present=True,
            entered_at=100.0,
            last_seen_at=120.0,
        )

        service._maybe_checked_in_stare_event("scope-1", "小羊", state, 119.0)
        service._maybe_checked_in_stare_event("scope-1", "小羊", state, 121.0)
        service._maybe_checked_in_stare_event("scope-1", "小羊", state, 190.0)

        self.assertEqual(self.event_count(service, "checked_in_stare"), 1)
        self.assertTrue(state.stare_triggered)

    def test_checked_in_leave_resets_stare_countdown(self) -> None:
        service = self.make_service()
        state = RemoteCheckedInPresence(
            present=True,
            entered_at=100.0,
            last_seen_at=121.0,
            last_stare_at=121.0,
            stare_triggered=True,
        )
        service._checked_in_presence[("scope-1", "小羊")] = state

        service._mark_absent_checked_in_names("scope-1", set(), 124.0)
        service._handle_checked_in_presence(
            "scope-1",
            "小羊",
            125.0,
            tenant_id="tenant-a",
            emit_repeat=False,
        )
        service._maybe_checked_in_stare_event("scope-1", "小羊", state, 144.0)
        service._maybe_checked_in_stare_event("scope-1", "小羊", state, 146.0)

        self.assertEqual(self.event_count(service, "checked_in_stare"), 1)
        self.assertEqual(state.entered_at, 125.0)
        self.assertTrue(state.stare_triggered)

    def test_stranger_stare_state_is_independent_per_person(self) -> None:
        service = self.make_service()
        first = RemoteStrangerPresence(
            present=True,
            entered_at=100.0,
            last_seen_at=120.0,
        )
        second = RemoteStrangerPresence(
            present=True,
            entered_at=100.0,
            last_seen_at=120.0,
        )

        service._maybe_stranger_stare_event("scope-1", "track:1", first, 121.0)
        service._maybe_stranger_stare_event("scope-1", "track:2", second, 122.0)
        service._maybe_stranger_stare_event("scope-1", "track:1", first, 190.0)

        self.assertEqual(self.event_count(service, "stranger_stare"), 2)
        self.assertTrue(first.stare_triggered)
        self.assertTrue(second.stare_triggered)

    def test_stranger_leave_resets_stare_countdown(self) -> None:
        service = self.make_service()
        state = RemoteStrangerPresence(
            present=True,
            entered_at=100.0,
            last_seen_at=121.0,
            last_stare_at=121.0,
            stare_triggered=True,
        )
        service._stranger_presence[("scope-1", "track:1")] = state

        service._mark_absent_stranger_keys("scope-1", set(), 124.0)
        service._handle_stranger_presence("scope-1", "track:1", 125.0, "male")
        service._maybe_stranger_stare_event("scope-1", "track:1", state, 144.0)
        service._maybe_stranger_stare_event("scope-1", "track:1", state, 146.0)

        self.assertEqual(self.event_count(service, "stranger_stare"), 1)
        self.assertEqual(state.entered_at, 125.0)
        self.assertTrue(state.stare_triggered)


if __name__ == "__main__":
    unittest.main()

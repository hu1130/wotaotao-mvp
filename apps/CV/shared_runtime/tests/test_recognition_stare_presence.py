from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path


repo_root = Path(__file__).resolve().parents[2]
server_path = str(repo_root / "server_deploy")
if server_path not in sys.path:
    sys.path.insert(0, server_path)
sys.modules.pop("config", None)
core_pkg = types.ModuleType("core")
core_pkg.__path__ = [
    str(repo_root / "shared_runtime" / "core"),
    str(repo_root / "server_deploy" / "core"),
]
sys.modules["core"] = core_pkg

from core.recognition_pipeline import (  # noqa: E402
    CheckedInPresence,
    RecognitionPipeline,
    StrangerPresence,
)


class FakeEventBus:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def checked_in_stare(self, name: str) -> None:
        self.events.append(("checked_in_stare", {"name": name}))

    def stranger_stare(self, salutation: str | None = None) -> None:
        self.events.append(("stranger_stare", {"salutation": salutation}))


class RecognitionStarePresenceTests(unittest.TestCase):
    def make_pipeline(self) -> RecognitionPipeline:
        pipeline = RecognitionPipeline.__new__(RecognitionPipeline)
        pipeline.checked_in_presence = {}
        pipeline.stranger_presence = {}
        pipeline.event_bus = FakeEventBus()
        pipeline.repeat_feedback_times = {}
        pipeline.stranger_followup_suppressed_until = 0.0
        return pipeline

    def event_count(self, pipeline: RecognitionPipeline, event_type: str) -> int:
        return sum(1 for current, _ in pipeline.event_bus.events if current == event_type)

    def test_checked_in_stare_triggers_once_per_presence(self) -> None:
        pipeline = self.make_pipeline()
        state = CheckedInPresence(
            present=True,
            entered_at=100.0,
            last_seen_at=120.0,
        )
        pipeline.checked_in_presence["小羊"] = state

        pipeline._handle_checked_in_presence("小羊", 119.0)
        pipeline._handle_checked_in_presence("小羊", 121.0)
        pipeline._handle_checked_in_presence("小羊", 190.0)

        self.assertEqual(self.event_count(pipeline, "checked_in_stare"), 1)
        self.assertTrue(state.stare_triggered)

    def test_checked_in_leave_resets_stare_countdown(self) -> None:
        pipeline = self.make_pipeline()
        state = CheckedInPresence(
            present=True,
            entered_at=100.0,
            last_seen_at=121.0,
            last_stare_at=121.0,
            stare_triggered=True,
        )
        pipeline.checked_in_presence["小羊"] = state

        pipeline._mark_absent_checked_in_names(set(), 124.0)
        pipeline._handle_checked_in_presence("小羊", 125.0)
        pipeline._handle_checked_in_presence("小羊", 144.0)
        pipeline._handle_checked_in_presence("小羊", 146.0)

        self.assertEqual(self.event_count(pipeline, "checked_in_stare"), 1)
        self.assertEqual(state.entered_at, 125.0)
        self.assertTrue(state.stare_triggered)

    def test_recorded_stranger_stare_triggers_once_per_presence(self) -> None:
        pipeline = self.make_pipeline()
        state = StrangerPresence(
            present=True,
            entered_at=100.0,
            last_seen_at=120.0,
        )
        pipeline.stranger_presence["visitor:001"] = state

        pipeline._handle_stranger_presence("visitor:001", 119.0, "female")
        pipeline._handle_stranger_presence("visitor:001", 121.0, "female")
        pipeline._handle_stranger_presence("visitor:001", 190.0, "female")

        self.assertEqual(self.event_count(pipeline, "stranger_stare"), 1)
        self.assertTrue(state.stare_triggered)

    def test_track_only_stranger_does_not_trigger_stare(self) -> None:
        pipeline = self.make_pipeline()
        pipeline.stranger_presence["track:1"] = StrangerPresence(
            present=True,
            entered_at=100.0,
            last_seen_at=120.0,
        )

        pipeline._handle_stranger_presence("track:1", 190.0, "female")

        self.assertEqual(self.event_count(pipeline, "stranger_stare"), 0)


if __name__ == "__main__":
    unittest.main()

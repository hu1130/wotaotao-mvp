from __future__ import annotations

import unittest

from core.person_sessions.manager import PersonConversationManager
from core.person_sessions.models import PersonSessionState


class FakeMemory:
    def __init__(self) -> None:
        self.started: list[tuple] = []
        self.ended: list[tuple] = []
        self.turns: list[dict] = []
        self.context: list[dict] = []

    def start_conversation(self, **kwargs) -> None:
        self.started.append(tuple(kwargs.values()))

    def append_turn(self, **kwargs) -> None:
        self.turns.append(kwargs)

    def recent_context(self, person_id: str, *, limit: int = 6) -> list[dict]:
        return self.context[-limit:]

    def end_conversation(self, conversation_id: str, *, reason: str) -> None:
        self.ended.append((conversation_id, reason))

    def close(self) -> None:
        return


def face(name: str | None, *, track_id: int = 1, x: int = 100) -> dict:
    return {
        "name": name,
        "recognized": bool(name),
        "track_id": track_id,
        "similarity": 0.8,
        "bbox": [x, 100, x + 180, 300],
    }


class PersonConversationManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.memory = FakeMemory()
        self.manager = PersonConversationManager(
            self.memory,
            acquire_seconds=2.0,
            absent_seconds=15.0,
            silent_release_seconds=180.0,
        )

    def observe(self, faces: list[dict], now: float):
        return self.manager.observe(
            "frontdesk-001",
            faces,
            frame_width=1280,
            frame_height=720,
            now=now,
        )

    def test_stable_person_acquires_and_absence_ends_session(self) -> None:
        candidate = self.observe([face("张伟")], 100.0)
        self.assertEqual(candidate.state, PersonSessionState.CANDIDATE)

        active = self.observe([face("张伟")], 102.1)
        self.assertEqual(active.state, PersonSessionState.ACTIVE)
        self.assertEqual(active.owner_name, "张伟")
        self.assertTrue(active.conversation_id)
        self.assertEqual(len(self.memory.started), 1)

        grace = self.observe([], 110.0)
        self.assertEqual(grace.state, PersonSessionState.OWNER_GRACE)

        still_grace = self.observe([], 120.0)
        self.assertEqual(still_grace.owner_name, "张伟")
        self.assertEqual(still_grace.state, PersonSessionState.OWNER_GRACE)

        cleared = self.observe([], 125.1)
        self.assertEqual(cleared.owner_name, "")
        self.assertEqual(cleared.state, PersonSessionState.IDLE)
        self.assertEqual(self.memory.ended, [(active.conversation_id, "owner_absent")])

    def test_replacement_candidate_hides_absent_owner_and_switches_after_acquire(self) -> None:
        self.observe([face("张伟")], 100.0)
        active = self.observe([face("张伟")], 102.1)
        self.observe([], 110.0)

        replacement_pending = self.observe([face("李雷", track_id=2)], 111.0)
        self.assertEqual(replacement_pending.state, PersonSessionState.CANDIDATE)
        self.assertEqual(replacement_pending.owner_name, "")
        self.assertEqual(replacement_pending.owner_id, "")
        self.assertEqual(replacement_pending.conversation_id, "")
        self.assertFalse(replacement_pending.memory_read_allowed)
        self.assertFalse(replacement_pending.memory_write_allowed)

        switched = self.observe([face("李雷", track_id=2)], 113.1)
        self.assertEqual(switched.owner_name, "李雷")
        self.assertNotEqual(switched.conversation_id, active.conversation_id)
        self.assertEqual(self.memory.ended, [(active.conversation_id, "owner_replaced")])
        self.assertEqual(len(self.memory.started), 2)

    def test_present_but_silent_releases_physical_voice_only(self) -> None:
        self.observe([face("张伟")], 100.0)
        active = self.observe([face("张伟")], 102.1)
        suspended = self.observe([face("张伟")], 282.2)

        self.assertEqual(suspended.state, PersonSessionState.SUSPENDED_IDLE)
        self.assertEqual(suspended.conversation_id, active.conversation_id)
        self.assertTrue(suspended.should_release_voice)
        resumed = self.manager.note_speech("frontdesk-001", now=283.0)
        self.assertEqual(resumed.state, PersonSessionState.ACTIVE)
        self.assertEqual(resumed.conversation_id, active.conversation_id)

    def test_bystanders_keep_owner_memory_and_personal_attribution(self) -> None:
        self.memory.context = [
            {"role": "user", "content": "上次的问题"},
            {"role": "assistant", "content": "上次的回答"},
        ]
        self.observe([face("张伟")], 100.0)
        active = self.observe([face("张伟")], 102.1)
        with_bystander = self.observe(
            [face("张伟"), face("李雷", track_id=2, x=500), face(None, track_id=3)],
            103.0,
        )

        self.assertTrue(with_bystander.bystanders_present)
        self.assertEqual(with_bystander.owner_name, "张伟")
        self.assertEqual(with_bystander.conversation_id, active.conversation_id)
        self.assertTrue(with_bystander.memory_read_allowed)
        self.assertTrue(with_bystander.memory_write_allowed)
        self.assertEqual(
            self.manager.recent_context(with_bystander),
            self.memory.context,
        )
        self.manager.append_turn(
            with_bystander,
            user_text="我的项目进展怎么样",
            assistant_text="我记得你上次提到的项目。",
        )
        self.assertTrue(self.memory.turns[0]["attributed"])
        self.assertEqual(self.memory.turns[0]["privacy_reason"], "")

    def test_participant_changes_do_not_advance_epoch_or_taint_turn(self) -> None:
        self.observe([face("张伟")], 100.0)
        started = self.observe([face("张伟")], 102.1)
        with_bystander = self.observe(
            [face("张伟"), face("李雷", track_id=2, x=500)],
            103.0,
        )
        self.assertEqual(with_bystander.privacy_epoch, started.privacy_epoch)
        private_again = self.observe([face("张伟")], 104.0)
        self.assertTrue(private_again.memory_read_allowed)
        self.assertEqual(private_again.privacy_epoch, started.privacy_epoch)
        self.manager.append_turn(
            private_again,
            user_text="请记住这次公开交流",
            assistant_text="收到",
        )
        self.assertTrue(self.memory.turns[-1]["attributed"])
        self.assertEqual(self.memory.turns[-1]["privacy_reason"], "")

    def test_server_supplied_stable_person_id_is_used(self) -> None:
        observed = self.manager.observe(
            "frontdesk-001",
            [{**face("张伟"), "person_id": "employee:stable-uuid"}],
            frame_width=1280,
            frame_height=720,
            now=100.0,
        )
        self.assertEqual(observed.state, PersonSessionState.CANDIDATE)
        active = self.manager.observe(
            "frontdesk-001",
            [{**face("张伟"), "person_id": "employee:stable-uuid"}],
            frame_width=1280,
            frame_height=720,
            now=102.1,
        )
        self.assertEqual(active.owner_id, "employee:stable-uuid")

    def test_snapshot_exposes_default_tenant_scope(self) -> None:
        snapshot = self.manager.get("frontdesk-001", now=100.0)
        self.assertEqual(snapshot.tenant_id, "default")
        self.assertEqual(snapshot.to_dict()["tenant_id"], "default")


if __name__ == "__main__":
    unittest.main()

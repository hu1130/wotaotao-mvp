from __future__ import annotations

import unittest

from core.avatar_event_dispatcher import RemoteAvatarEventDispatcher


class CapturingDispatcher(RemoteAvatarEventDispatcher):
    def __init__(self) -> None:
        super().__init__("http://avatar.test")
        self.payloads: list[dict] = []

    def _post(self, payload: dict) -> bool:
        self.payloads.append(payload)
        return True


class AvatarEventDispatcherTests(unittest.TestCase):
    def test_check_in_always_uses_check_in_speech_type(self) -> None:
        dispatcher = CapturingDispatcher()

        result = dispatcher.emit(
            "check_in",
            {
                "name": "小羊",
                "tenant_id": "computer-mine",
                "is_first": False,
                "is_returning": True,
            },
        )

        self.assertTrue(result.action_sent)
        self.assertTrue(result.speech_sent)
        self.assertEqual(result.speech_type, "check_in")
        self.assertEqual(dispatcher.payloads[0]["type"], "check_in")
        self.assertEqual(dispatcher.payloads[1]["type"], "speech")
        self.assertEqual(dispatcher.payloads[1]["event_type"], "check_in")

    def test_first_check_in_also_uses_check_in_speech_type(self) -> None:
        dispatcher = CapturingDispatcher()

        result = dispatcher.emit(
            "check_in",
            {
                "name": "小羊",
                "tenant_id": "computer-mine",
                "is_first": True,
                "is_returning": False,
            },
        )

        self.assertTrue(result.speech_sent)
        self.assertEqual(result.speech_type, "check_in")
        self.assertEqual(dispatcher.payloads[1]["event_type"], "check_in")

    def test_custom_speech_posts_dynamic_speech_payload(self) -> None:
        dispatcher = CapturingDispatcher()

        result = dispatcher.emit_custom_speech(
            text="are you ok",
            tenant_id="computer-mine",
            event_type="arrival_task",
            name="小羊",
            priority=88,
            source="person_arrival_task",
            dedup_key="task-1",
        )

        self.assertTrue(result.speech_sent)
        self.assertEqual(len(dispatcher.payloads), 1)
        payload = dispatcher.payloads[0]
        self.assertEqual(payload["type"], "speech")
        self.assertEqual(payload["event_type"], "arrival_task")
        self.assertEqual(payload["tenant_id"], "computer-mine")
        self.assertEqual(payload["text"], "are you ok")
        self.assertEqual(payload["source"], "person_arrival_task")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from core.dialog_actions import (
    ACTION_ADJUST_SYSTEM_VOLUME,
    ACTION_CAPTURE_FACE_ENROLL,
    DialogAgentIntentRouter,
    DialogActionExecutor,
    DialogActionProposal,
    INPUT_REQUIRED,
)


class DialogActionRouterTests(unittest.TestCase):
    def test_plain_silence_does_not_route_to_volume_action(self) -> None:
        router = DialogAgentIntentRouter()

        proposal = router.route("开启静音。")

        self.assertIsNone(proposal)

    def test_system_mute_phrase_does_not_route_to_system_volume_action(self) -> None:
        router = DialogAgentIntentRouter()

        proposal = router.route("电脑音量静音。")

        self.assertIsNone(proposal)

    def test_voice_description_does_not_route_to_volume_action(self) -> None:
        router = DialogAgentIntentRouter()

        for text in ("你的声音很好听。", "这个声音有点奇怪。", "声音怎么样？"):
            with self.subTest(text=text):
                self.assertIsNone(router.route(text))

    def test_ambiguous_volume_control_can_still_clarify(self) -> None:
        router = DialogAgentIntentRouter()

        proposal = router.route("帮我调整一下声音。")

        self.assertIsNotNone(proposal)
        assert proposal is not None
        self.assertEqual(proposal.action, "clarify_volume_direction")

    def test_volume_followup_uses_current_conversation_context(self) -> None:
        router = DialogAgentIntentRouter()

        proposal = router.route(
            "大一点。",
            [
                {"role": "user", "content": "帮我把音量调大一点。"},
                {"role": "assistant", "content": "你看看这个音量怎么样。"},
            ],
        )

        self.assertIsNotNone(proposal)
        assert proposal is not None
        self.assertEqual(proposal.action, ACTION_ADJUST_SYSTEM_VOLUME)
        self.assertEqual(proposal.params["direction"], "increase")
        self.assertEqual(proposal.params["response_style"], "now_check")
        self.assertEqual(proposal.params["target"], "system")
        self.assertEqual(proposal.reason, "volume_direction_clarification_followup")

    def test_face_capture_without_name_requires_browser_input(self) -> None:
        executor = DialogActionExecutor()

        result = executor.execute(
            DialogActionProposal(
                action=ACTION_CAPTURE_FACE_ENROLL,
                confidence=1.0,
                params={},
                source="test",
            ),
            user_text="帮我录入人脸",
            conversation_id="conv-1",
            device_id="frontdesk-1",
            tenant_id="tenant-a",
        )

        self.assertTrue(result.handled)
        self.assertEqual(result.status, INPUT_REQUIRED)
        self.assertEqual(result.task_id, "")
        self.assertTrue(result.payload["requiresBrowserInput"])
        self.assertEqual(result.payload["inputKind"], "face_capture_employee_name")


if __name__ == "__main__":
    unittest.main()

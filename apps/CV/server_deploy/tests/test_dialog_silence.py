import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from core.dialog_silence import (
    ACTION_MUTE,
    ACTION_NONE,
    ACTION_SUPPRESS,
    ACTION_WAKE,
    build_silence_status_text,
    get_dialog_silence_state_store,
    resolve_dialog_silence,
)
from core.speech_streaming.pipeline import VoicePipelineSession


class DialogSilenceTests(unittest.TestCase):
    def test_silence_command_uses_dynamic_assistant_name(self) -> None:
        result = resolve_dialog_silence(
            "静音",
            muted=False,
            assistant_name="小鹿",
            wake_aliases=("小鹿", "鹿鹿"),
        )

        self.assertEqual(result.action, ACTION_MUTE)
        self.assertEqual(result.assistant_name, "小鹿")
        self.assertIn("喊小鹿", result.response_text)
        self.assertEqual(result.status_text, "静音中，喊小鹿唤醒我")

    def test_enable_silence_phrase_is_business_silence(self) -> None:
        result = resolve_dialog_silence(
            "开启静音。",
            muted=False,
            assistant_name="小鹿",
            wake_aliases=("小鹿", "鹿鹿"),
        )

        self.assertEqual(result.action, ACTION_MUTE)
        self.assertEqual(result.status_text, "静音中，喊小鹿唤醒我")

    def test_turn_off_voice_phrase_is_business_silence(self) -> None:
        result = resolve_dialog_silence(
            "把声音关掉。",
            muted=False,
            assistant_name="小鹿",
            wake_aliases=("小鹿", "鹿鹿"),
        )

        self.assertEqual(result.action, ACTION_MUTE)
        self.assertEqual(result.status_text, "静音中，喊小鹿唤醒我")

    def test_wake_prefixed_silence_command_is_handled(self) -> None:
        result = resolve_dialog_silence(
            "鹿鹿，别说话了",
            muted=False,
            assistant_name="小鹿",
            wake_aliases=("小鹿", "鹿鹿"),
        )

        self.assertEqual(result.action, ACTION_MUTE)
        self.assertEqual(result.matched_alias, "鹿鹿")
        self.assertEqual(result.status_text, build_silence_status_text("小鹿"))

    def test_muted_non_wake_suppresses_dialog(self) -> None:
        result = resolve_dialog_silence(
            "你听得到吗",
            muted=True,
            assistant_name="小鹿",
            wake_aliases=("小鹿", "鹿鹿"),
        )

        self.assertEqual(result.action, ACTION_SUPPRESS)
        self.assertEqual(result.status_text, "静音中，喊小鹿唤醒我")
        self.assertEqual(result.response_text, "")

    def test_muted_wake_only_resumes_with_feedback(self) -> None:
        result = resolve_dialog_silence(
            "小鹿",
            muted=True,
            assistant_name="小鹿",
            wake_aliases=("小鹿", "鹿鹿"),
        )

        self.assertEqual(result.action, ACTION_WAKE)
        self.assertEqual(result.route_text, "")
        self.assertEqual(result.response_text, "我在，已解除静音。")

    def test_muted_wake_with_command_resumes_and_routes_command(self) -> None:
        result = resolve_dialog_silence(
            "小鹿，帮我查公司资料",
            muted=True,
            assistant_name="小鹿",
            wake_aliases=("小鹿", "鹿鹿"),
        )

        self.assertEqual(result.action, ACTION_WAKE)
        self.assertEqual(result.route_text, "帮我查公司资料")
        self.assertEqual(result.response_text, "")

    def test_unrelated_text_is_not_silence_control(self) -> None:
        result = resolve_dialog_silence(
            "帮我查公司资料",
            muted=False,
            assistant_name="小鹿",
            wake_aliases=("小鹿", "鹿鹿"),
        )

        self.assertEqual(result.action, ACTION_NONE)
        self.assertEqual(result.route_text, "帮我查公司资料")

    def test_voice_session_suppresses_until_wake_name(self) -> None:
        sent: list[dict] = []

        async def sender(payload: dict) -> None:
            sent.append(payload)

        async def scenario() -> VoicePipelineSession:
            session = VoicePipelineSession(sender)
            session._resolve_avatar_persona = AsyncMock(
                return_value=SimpleNamespace(
                    assistant_name="小鹿",
                    wake_aliases=("小鹿", "鹿鹿"),
                )
            )
            session._speak_scene_response = AsyncMock(return_value="我先安静下来，需要时喊我就好。")

            muted = await session._handle_dialog_silence_control("静音")
            suppressed = await session._handle_dialog_silence_control("你还在吗")
            resumed = await session._handle_dialog_silence_control("小鹿")

            self.assertTrue(muted.handled)
            self.assertEqual(muted.reason, "dialog_silenced")
            self.assertTrue(suppressed.handled)
            self.assertEqual(suppressed.reason, "dialog_silenced")
            self.assertTrue(resumed.handled)
            self.assertEqual(resumed.reason, "dialog_resumed")
            return session

        session = asyncio.run(scenario())

        self.assertFalse(session._dialog_silenced)
        self.assertEqual(
            [item["active"] for item in sent if item.get("type") == "dialog_silence"],
            [True, True, False],
        )
        silence_events = [item for item in sent if item.get("type") == "dialog_silence"]
        self.assertIn("喊小鹿", silence_events[0]["responseText"])
        self.assertEqual(silence_events[1]["responseText"], "")

    def test_voice_session_wake_with_command_resumes_and_routes(self) -> None:
        async def sender(_payload: dict) -> None:
            return None

        async def scenario() -> tuple[VoicePipelineSession, object]:
            session = VoicePipelineSession(sender)
            session._dialog_silenced = True
            session._dialog_silence_status_text = "静音中，喊小鹿唤醒我"
            session._resolve_avatar_persona = AsyncMock(
                return_value=SimpleNamespace(
                    assistant_name="小鹿",
                    wake_aliases=("小鹿", "鹿鹿"),
                )
            )
            session._speak_scene_response = AsyncMock(return_value="我已经恢复啦。")
            result = await session._handle_dialog_silence_control("鹿鹿，帮我查资料")
            return session, result

        session, result = asyncio.run(scenario())

        self.assertFalse(result.handled)
        self.assertEqual(result.route_text, "帮我查资料")
        self.assertFalse(session._dialog_silenced)
        session._speak_scene_response.assert_not_awaited()

    def test_voice_silence_state_is_scoped_to_tenant_and_device(self) -> None:
        async def sender(_payload: dict) -> None:
            return None

        async def build_session() -> VoicePipelineSession:
            session = VoicePipelineSession(sender)
            session.tenant_id = "tenant-a"
            session.device_id = "frontdesk-1"
            session._resolve_avatar_persona = AsyncMock(
                return_value=SimpleNamespace(
                    assistant_name="小鹿",
                    wake_aliases=("小鹿", "鹿鹿"),
                )
            )
            session._speak_scene_response = AsyncMock(return_value="我先安静下来，需要时喊我就好。")
            return session

        async def scenario() -> object:
            first = await build_session()
            second = await build_session()
            await first._handle_dialog_silence_control("静音")
            return await second._handle_dialog_silence_control("你还在吗")

        try:
            result = asyncio.run(scenario())
        finally:
            get_dialog_silence_state_store().clear("tenant-a", "frontdesk-1")

        self.assertTrue(result.handled)
        self.assertEqual(result.reason, "dialog_silenced")


if __name__ == "__main__":
    unittest.main()

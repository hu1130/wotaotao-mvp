import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core.dialog_chat import DialogChatService, match_local_quick_reply
from core.dialog_wake_name import parse_wake_name
from core.person_memory.commands import route_person_memory_command


class DialogWakeNameTests(unittest.TestCase):
    def test_wake_name_only_returns_wake_only(self) -> None:
        result = parse_wake_name("叮当，你在吗")

        self.assertTrue(result.called)
        self.assertTrue(result.wake_only)
        self.assertEqual(result.matched_alias, "叮当")
        self.assertEqual(result.command_text, "")

    def test_wake_name_prefix_routes_remaining_command(self) -> None:
        result = parse_wake_name("叮当，你帮我记住我的生日是七月十五号")

        self.assertTrue(result.called)
        self.assertFalse(result.wake_only)
        self.assertEqual(
            result.command_text,
            "帮我记住我的生日是七月十五号",
        )
        command = route_person_memory_command(result.command_text)
        self.assertIsNotNone(command)
        self.assertEqual(command.action, "remember")

    def test_wake_name_alias_with_greeting(self) -> None:
        result = parse_wake_name("你好，小叮当，帮我查一下公司资料")

        self.assertTrue(result.called)
        self.assertFalse(result.wake_only)
        self.assertEqual(result.matched_alias, "小叮当")
        self.assertEqual(result.command_text, "帮我查一下公司资料")

    def test_wake_name_arrival_task_keeps_natural_command(self) -> None:
        result = parse_wake_name("叮当，以后我一过来你就跟我说“are you ok”")

        self.assertTrue(result.called)
        self.assertEqual(result.command_text, "以后我一过来你就跟我说“are you ok”")
        command = route_person_memory_command(result.command_text)
        self.assertIsNotNone(command)
        self.assertEqual(command.action, "arrival_task")
        self.assertEqual(command.content, "are you ok")

    def test_text_chat_wake_name_quick_reply(self) -> None:
        self.assertEqual(match_local_quick_reply("叮当"), "我在呢")

    def test_scene_reply_uses_model_prompt_instead_of_canonical_text(self) -> None:
        service = DialogChatService()
        service.api_base = "https://example.invalid/v1"
        service.api_key = "test-key"
        service.model = "test-model"
        service._post_chat_completion = Mock(
            return_value={
                "choices": [
                    {"message": {"content": "我在听呢，你直接说就好。"}}
                ]
            }
        )

        persona_service = Mock()
        persona_service.resolve.return_value = SimpleNamespace(
            chat_system_prompt="你是自然亲切的前台数字人。"
        )
        with patch(
            "core.dialog_chat.get_tenant_avatar_persona_service",
            return_value=persona_service,
        ):
            answer = service.scene_reply(
                scene="assistant_wake",
                user_text="叮当",
                tenant_id="tenant-a",
                required_facts=["我在呢"],
                response_goal="回应用户正在叫你。",
            )

        self.assertEqual(answer, "我在听呢，你直接说就好。")
        payload = service._post_chat_completion.call_args.args[0]
        self.assertEqual(payload["temperature"], 0.85)
        self.assertIn("业务场景：assistant_wake", payload["messages"][1]["content"])
        self.assertIn("我在呢", payload["messages"][1]["content"])
        self.assertNotEqual(answer, "我在呢")

    def test_dashscope_scene_reply_disables_thinking(self) -> None:
        service = DialogChatService()
        service.api_base = "https://dashscope.aliyuncs.com/compatible-mode/v1"
        service.api_key = "test-key"
        service.model = "qwen3.6-plus"
        service.enable_thinking = False
        service._post_chat_completion = Mock(
            return_value={"choices": [{"message": {"content": "我在听。"}}]}
        )

        persona_service = Mock()
        persona_service.resolve.return_value = SimpleNamespace(
            chat_system_prompt="你是自然亲切的前台数字人。"
        )
        with patch(
            "core.dialog_chat.get_tenant_avatar_persona_service",
            return_value=persona_service,
        ):
            service.scene_reply(
                scene="assistant_wake",
                user_text="叮当",
                tenant_id="tenant-a",
                required_facts=["我在呢"],
            )

        payload = service._post_chat_completion.call_args.args[0]
        self.assertEqual(payload["model"], "qwen3.6-plus")
        self.assertIs(payload["enable_thinking"], False)


if __name__ == "__main__":
    unittest.main()

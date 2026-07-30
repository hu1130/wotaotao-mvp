from __future__ import annotations

import unittest

from core.person_sessions.context_intent import PersonContextIntentRouter


class PersonContextIntentRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.router = PersonContextIntentRouter()

    def test_verified_identity_is_answered_from_server_context(self) -> None:
        reply = self.router.route(
            "你知道我是谁吗？",
            person_name="小游",
            identity_verified=True,
        )

        self.assertIsNotNone(reply)
        assert reply is not None
        self.assertTrue(reply.identity_verified)
        self.assertIn("身份已确认", reply.text)
        self.assertIn("姓名：小游", reply.required_facts[0])
        self.assertIn("不要每次固定", reply.response_goal)

    def test_unverified_name_is_not_disclosed_as_identity(self) -> None:
        reply = self.router.route(
            "我是谁？",
            person_name="客户端伪造姓名",
            identity_verified=False,
        )

        self.assertIsNotNone(reply)
        assert reply is not None
        self.assertFalse(reply.identity_verified)
        self.assertNotIn("客户端伪造姓名", reply.text)
        self.assertNotIn("客户端伪造姓名", " ".join(reply.required_facts))
        self.assertIn("尚未确认", reply.text)

    def test_unrelated_who_question_is_not_intercepted(self) -> None:
        self.assertIsNone(
            self.router.route(
                "公司负责人是谁？",
                person_name="小游",
                identity_verified=True,
            )
        )

    def test_assistant_identity_question_is_not_recall_context(self) -> None:
        self.assertIsNone(
            self.router.route(
                "我问你是谁？",
                person_name="小游",
                identity_verified=True,
                context=[{"role": "user", "content": "刚才问过公司的产品。"}],
            )
        )

    def test_verified_conversation_recall_uses_recent_user_history(self) -> None:
        reply = self.router.route(
            "你记得我上次跟你说的啥吗？",
            person_name="小游",
            identity_verified=True,
            context=[
                {"role": "user", "content": "去哪里吃饭？"},
                {"role": "assistant", "content": "楼下的和平饭店。"},
                {"role": "user", "content": "你们公司做什么产品呢？"},
                {"role": "assistant", "content": "我们做企业级AI产品。"},
            ],
        )

        self.assertIsNotNone(reply)
        assert reply is not None
        self.assertEqual(reply.intent, "conversation_recall")
        self.assertEqual(reply.source_messages, 2)
        self.assertIn("你们公司做什么产品呢", reply.required_facts[0])
        self.assertIn("去哪里吃饭", reply.required_facts[0])
        self.assertNotIn("你说", reply.text)
        self.assertNotIn("我回", reply.text)
        self.assertIn("不要直接照抄", " ".join(reply.constraints))

    def test_conversation_recall_skips_previous_recall_questions(self) -> None:
        reply = self.router.route(
            "我刚才跟你说了什么？",
            person_name="小游",
            identity_verified=True,
            context=[
                {"role": "user", "content": "去哪里吃饭？"},
                {"role": "assistant", "content": "楼下的和平饭店。"},
                {"role": "user", "content": "我上次跟你说的啥？"},
                {"role": "assistant", "content": "我没记住。"},
            ],
        )

        self.assertIsNotNone(reply)
        assert reply is not None
        self.assertIn("去哪里吃饭", reply.required_facts[0])
        self.assertNotIn("我上次跟你说的啥？", reply.text)

    def test_yesterday_recall_uses_dated_records_before_recent_context(self) -> None:
        reply = self.router.route(
            "那你现在记得昨天我们聊了什么吗？",
            person_name="小游",
            identity_verified=True,
            context=[
                {"role": "user", "content": "刚刚这一句不该被当成昨天"},
            ],
            dated_recall={
                "target_date": "2026-07-22",
                "target_label": "昨天",
                "turns": (
                    {
                        "user_text": "你们公司的产品是什么？",
                        "assistant_text": "我们做企业级 AI 数字人。",
                    },
                    {
                        "user_text": "你的名字是什么？",
                        "assistant_text": "我叫叮当。",
                    },
                ),
            },
        )

        self.assertIsNotNone(reply)
        assert reply is not None
        self.assertIn("昨天", reply.text)
        self.assertIn("你们公司的产品是什么", reply.required_facts[0])
        self.assertIn("你的名字是什么", reply.required_facts[0])
        self.assertNotIn("你说", reply.text)
        self.assertNotIn("我回", reply.text)
        self.assertNotIn("刚刚这一句", reply.text)

    def test_verified_asr_noisy_yesterday_recall_uses_dated_records(self) -> None:
        reply = self.router.route(
            "继昨天我们说过啥吗？",
            person_name="小游",
            identity_verified=True,
            dated_recall={
                "target_date": "2026-07-22",
                "target_label": "昨天",
                "summary": "讨论了数字人前台和考勤签退测试。",
                "turns": (),
                "source_turn_count": 4,
            },
        )

        self.assertIsNotNone(reply)
        assert reply is not None
        self.assertEqual(reply.intent, "conversation_recall")
        self.assertEqual(reply.source_messages, 4)
        self.assertIn("昨天我们主要聊到", reply.required_facts[0])
        self.assertIn("考勤签退测试", reply.required_facts[0])

    def test_dated_recall_sanitizes_third_person_daily_summary(self) -> None:
        reply = self.router.route(
            "昨天我们聊了什么？",
            person_name="小游",
            identity_verified=True,
            dated_recall={
                "target_date": "2026-07-22",
                "target_label": "昨天",
                "summary": "用户聊了签退时间和对话回忆。",
                "turns": (),
                "source_turn_count": 3,
            },
        )

        self.assertIsNotNone(reply)
        assert reply is not None
        self.assertIn("昨天我们主要聊到", reply.required_facts[0])
        self.assertIn("签退时间和对话回忆", reply.required_facts[0])
        self.assertNotIn("用户", reply.required_facts[0])
        self.assertNotIn("用户聊了", reply.required_facts[0])

    def test_yesterday_recall_reports_missing_dated_records(self) -> None:
        reply = self.router.route(
            "昨天聊了啥？",
            person_name="小游",
            identity_verified=True,
            dated_recall={
                "target_date": "2026-07-22",
                "target_label": "昨天",
                "turns": (),
            },
        )

        self.assertIsNotNone(reply)
        assert reply is not None
        self.assertIn("没有找到昨天", reply.text)

    def test_unverified_conversation_cannot_read_history(self) -> None:
        reply = self.router.route(
            "我们之前聊了什么？",
            person_name="客户端姓名",
            identity_verified=False,
            context=[{"role": "user", "content": "敏感历史"}],
        )

        self.assertIsNotNone(reply)
        assert reply is not None
        self.assertFalse(reply.identity_verified)
        self.assertNotIn("敏感历史", reply.text)
        self.assertNotIn("敏感历史", " ".join(reply.required_facts))
        self.assertIn("不能读取", reply.text)

    def test_ambiguous_conversation_recall_statement_asks_clarification(self) -> None:
        reply = self.router.route(
            "昨天我们聊了很多。",
            person_name="小游",
            identity_verified=True,
            context=[{"role": "user", "content": "不应该读取这一句"}],
            dated_recall={
                "target_date": "2026-07-22",
                "target_label": "昨天",
                "summary": "不应该读取的历史摘要",
            },
        )

        self.assertIsNotNone(reply)
        assert reply is not None
        self.assertTrue(reply.needs_clarification)
        self.assertIn("你是想让我回忆昨天我们聊过什么吗", reply.required_facts[0])
        self.assertNotIn("不应该读取", reply.text)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import inspect
import unittest

from config import PERSON_MEMORY_RETRIEVAL_TOP_K, PERSON_MEMORY_SESSION_TOP_K
from core.person_memory.commands import route_person_memory_command
from core.person_memory.extractor import PersonMemoryExtractor
from core.person_memory.migrations import _migration_statements
from core.person_memory.models import DailySummaryCandidate
from core.person_memory.models import RetrievedPersonMemory
from core.person_memory.repository import PostgresPersonMemoryRepository
from core.person_memory.service import PersonMemoryService


class FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:
        return

    def json(self) -> dict:
        return self._payload


class FakeHttpSession:
    def __init__(self, content: dict):
        self.content = content

    def post(self, *args, **kwargs) -> FakeResponse:
        return FakeResponse(
            {"choices": [{"message": {"content": json.dumps(self.content, ensure_ascii=False)}}]}
        )

    def close(self) -> None:
        return


class FakeRepository:
    def __init__(self):
        self.retrieve_calls: list[dict] = []
        self.arrival_task_calls: list[dict] = []
        self.cancel_arrival_task_calls: list[dict] = []
        self.daily_summary_calls: list[dict] = []
        self.daily_summary_by_date: dict[str, dict] = {}
        self.explicit_facts: tuple[dict, ...] = (
            {
                "fact_id": "explicit-1",
                "category": "personal_context",
                "content": "用户明确要求记住他的咖啡偏好是冰美式",
                "confidence": 0.99,
                "salience": 0.9,
            },
        )
        self.daily_summaries: tuple[dict, ...] = ()
        self.daily_candidates: tuple[DailySummaryCandidate, ...] = ()
        self.daily_turns: tuple[dict, ...] = ()
        self.skipped_daily_summaries: list[dict] = []

    def retrieve_memory(self, person_id, *, query, query_embedding, top_k):
        self.retrieve_calls.append(
            {
                "person_id": person_id,
                "query": query,
                "query_embedding": query_embedding,
                "top_k": top_k,
            }
        )
        return RetrievedPersonMemory(
            person_id=person_id,
            profile={"interaction_preferences": "喜欢简洁直接的回答"},
            facts=(
                {
                    "fact_id": "fact-1",
                    "category": "preference",
                    "content": "平时喜欢喝美式咖啡",
                    "confidence": 0.97,
                    "salience": 0.8,
                    "reinforcement_count": 2,
                },
            ),
        )

    def list_explicit_facts(self, person_id):
        return self.explicit_facts

    def retrieve_daily_summaries(self, person_id, *, query, query_embedding, top_k):
        self.daily_summary_calls.append(
            {
                "person_id": person_id,
                "query": query,
                "query_embedding": query_embedding,
                "top_k": top_k,
            }
        )
        return self.daily_summaries

    def load_daily_summary(self, *, person_id, summary_date):
        return self.daily_summary_by_date.get(summary_date)

    def load_daily_summary_turns(self, **kwargs):
        return self.daily_turns

    def memory_status(self):
        return {"pending": 0, "running": 0, "dead": 0, "oldestPendingSeconds": 0}

    def upsert_arrival_task(self, **kwargs):
        self.arrival_task_calls.append(kwargs)
        return {
            "taskId": "task-1",
            "tenantId": kwargs["tenant_id"],
            "creatorPersonId": kwargs["creator_person_id"],
            "creatorName": kwargs["creator_name"],
            "targetPersonId": kwargs["target_person_id"],
            "targetName": kwargs["target_name"],
            "content": kwargs["content"],
            "exactText": kwargs["exact_text"],
            "repeat": kwargs["repeat"],
            "replaced": 0,
        }

    def cancel_arrival_tasks(self, **kwargs):
        self.cancel_arrival_task_calls.append(kwargs)
        return 1

    def find_daily_summary_candidates(self, *, limit):
        return self.daily_candidates[:limit]

    def upsert_daily_summary(self, **kwargs):
        self.daily_summary_calls.append(kwargs)
        return {
            "summaryId": "summary-1",
            "personId": kwargs["person_id"],
            "tenantId": kwargs["tenant_id"],
            "summaryDate": kwargs["summary_date"],
            "sourceTurnCount": kwargs["source_turn_count"],
            "embedding": bool(kwargs["embedding"]),
        }

    def mark_daily_summary_skipped(self, **kwargs):
        self.skipped_daily_summaries.append(kwargs)
        return {"status": "empty", "summaryDate": kwargs["summary_date"]}


class FakeExtractor:
    ready = True
    daily_summary = "用户最近在推进客户演示，偏好回答直接给结论。"

    def close(self) -> None:
        return

    def summarize_daily(self, **kwargs) -> str:
        return self.daily_summary


class FakeEmbeddingClient:
    ready = True

    def embed_query(self, text: str) -> list[float]:
        return [0.1, 0.2]


class PersonMemoryCommandTests(unittest.TestCase):
    def test_routes_explicit_remember(self) -> None:
        command = route_person_memory_command("请帮我记住我喜欢喝美式咖啡")
        self.assertIsNotNone(command)
        assert command is not None
        self.assertEqual(command.action, "remember")
        self.assertEqual(command.content, "我喜欢喝美式咖啡")

    def test_forget_requires_separate_confirmation(self) -> None:
        request = route_person_memory_command("请忘掉我喜欢喝美式咖啡")
        confirm = route_person_memory_command("确认")
        self.assertEqual(request.action, "request_forget")
        self.assertEqual(confirm.action, "confirm_forget")

    def test_routes_self_arrival_exact_speech_task(self) -> None:
        command = route_person_memory_command("以后我一过来你就跟我说“are you ok”")

        self.assertIsNotNone(command)
        assert command is not None
        self.assertEqual(command.action, "arrival_task")
        self.assertEqual(command.content, "are you ok")
        self.assertEqual(command.target_name, "")
        self.assertTrue(command.exact)
        self.assertTrue(command.repeat)

    def test_routes_self_arrival_from_seen_me_asr_text(self) -> None:
        samples = [
            ("以后见到我要跟我说， are you？ OK？", "are you OK"),
            ("我说以后看到我，我一定要说 are you OK？", "are you OK"),
            ("以后看到我你就跟我说 are you ok", "are you ok"),
        ]

        for text, expected in samples:
            with self.subTest(text=text):
                command = route_person_memory_command(text)

                self.assertIsNotNone(command)
                assert command is not None
                self.assertEqual(command.action, "arrival_task")
                self.assertEqual(command.content, expected)
                self.assertEqual(command.target_name, "")
                self.assertFalse(command.exact)
                self.assertTrue(command.repeat)

    def test_routes_remember_prefixed_self_arrival_before_generic_memory(self) -> None:
        command = route_person_memory_command("记住以后看到我要跟我说 are you ok")

        self.assertIsNotNone(command)
        assert command is not None
        self.assertEqual(command.action, "arrival_task")
        self.assertEqual(command.content, "are you ok")
        self.assertEqual(command.target_name, "")
        self.assertTrue(command.repeat)

    def test_routes_self_arrival_plain_say_and_shout_update_phrasing(self) -> None:
        first = route_person_memory_command("以后看到我说大哥")
        second = route_person_memory_command("以后见到我喊”王总“")

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        assert first is not None
        assert second is not None
        self.assertEqual(first.action, "arrival_task")
        self.assertEqual(first.content, "大哥")
        self.assertFalse(first.exact)
        self.assertEqual(second.action, "arrival_task")
        self.assertEqual(second.content, "王总")
        self.assertTrue(second.exact)

    def test_routes_arrival_task_cancel_commands(self) -> None:
        latest = route_person_memory_command("取消刚才的到场提醒")
        self_task = route_person_memory_command("以后不要再见到我就说这个了")

        self.assertIsNotNone(latest)
        self.assertIsNotNone(self_task)
        assert latest is not None
        assert self_task is not None
        self.assertEqual(latest.action, "cancel_arrival_task")
        self.assertEqual(latest.content, "latest")
        self.assertEqual(self_task.action, "cancel_arrival_task")
        self.assertEqual(self_task.content, "self")

    def test_keeps_generic_remember_for_non_arrival_memory(self) -> None:
        command = route_person_memory_command("记住我喜欢喝冰美式")

        self.assertIsNotNone(command)
        assert command is not None
        self.assertEqual(command.action, "remember")
        self.assertEqual(command.content, "我喜欢喝冰美式")

    def test_routes_one_shot_target_arrival_instruction(self) -> None:
        command = route_person_memory_command("待会儿小王员工来了，骂他两句")

        self.assertIsNotNone(command)
        assert command is not None
        self.assertEqual(command.action, "arrival_task")
        self.assertEqual(command.content, "骂他两句")
        self.assertEqual(command.target_name, "小王")
        self.assertFalse(command.exact)
        self.assertFalse(command.repeat)

    def test_rejects_first_person_arrival_statements(self) -> None:
        for text in (
            "我要来面试的。",
            "我是来面试的。",
            "我来面试的。",
            "我要来咨询的。",
            "我们来参观的。",
            "待会儿我要来面试。",
        ):
            with self.subTest(text=text):
                self.assertIsNone(route_person_memory_command(text))

    def test_target_arrival_without_timing_requires_instruction(self) -> None:
        self.assertIsNone(route_person_memory_command("张三来了面试"))

        command = route_person_memory_command("张三来了提醒他面试")

        self.assertIsNotNone(command)
        assert command is not None
        self.assertEqual(command.action, "arrival_task")
        self.assertEqual(command.content, "面试")
        self.assertEqual(command.target_name, "张三")


class PersonMemoryExtractorTests(unittest.TestCase):
    def test_rejects_sensitive_and_low_confidence_facts(self) -> None:
        extractor = PersonMemoryExtractor()
        extractor.api_base = "http://example.test/v1"
        extractor.api_key = "test"
        extractor.model = "test-model"
        extractor.session = FakeHttpSession(
            {
                "profile_updates": {"interaction_preferences": "喜欢简洁回答"},
                "new_facts": [
                    {
                        "content": "用户喜欢简洁回答",
                        "category": "preference",
                        "confidence": 0.96,
                        "salience": 0.8,
                        "sensitive": False,
                        "source_turn_ids": ["turn-1"],
                    },
                    {
                        "content": "用户密码是 123456",
                        "category": "personal_context",
                        "confidence": 0.99,
                        "salience": 1.0,
                        "sensitive": False,
                        "source_turn_ids": ["turn-1"],
                    },
                    {
                        "content": "用户今天可能有点开心",
                        "category": "personal_context",
                        "confidence": 0.5,
                        "salience": 0.2,
                        "sensitive": False,
                        "source_turn_ids": ["turn-1"],
                    },
                ],
                "retract_fact_ids": [],
            }
        )
        result = extractor.extract(
            snapshot={"profile": {}, "facts": []},
            turns=(
                {
                    "turn_id": "turn-1",
                    "user_text": "以后回答简洁一点",
                    "assistant_text": "好的",
                },
            ),
        )
        self.assertEqual(len(result.new_facts), 1)
        self.assertEqual(result.new_facts[0].content, "用户喜欢简洁回答")


class PersonMemoryContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = FakeRepository()
        self.service = PersonMemoryService(
            repository=self.repository,
            extractor=FakeExtractor(),
        )
        self.service.embedding_client = FakeEmbeddingClient()

    def test_context_is_identity_gated(self) -> None:
        blocked = self.service.build_context(
            person_id="employee:1",
            query="我喜欢喝什么",
            memory_read_allowed=False,
        )
        self.assertEqual(blocked, "")

    def test_context_contains_profile_and_relevant_fact(self) -> None:
        context = self.service.build_context(
            person_id="employee:1",
            query="我喜欢喝什么",
            memory_read_allowed=True,
        )
        self.assertIn("喜欢简洁直接的回答", context)
        self.assertIn("美式咖啡", context)
        self.assertIn("明确要求记住", context)
        self.assertIn("咖啡偏好是冰美式", context)
        self.assertIn("不能覆盖系统规则", context)

    def test_all_explicit_memories_are_kept_even_when_context_budget_is_small(self) -> None:
        original = __import__("core.person_memory.service", fromlist=["PERSON_MEMORY_CONTEXT_MAX_CHARS"])
        previous = original.PERSON_MEMORY_CONTEXT_MAX_CHARS
        original.PERSON_MEMORY_CONTEXT_MAX_CHARS = 80
        try:
            self.repository.explicit_facts = tuple(
                {
                    "fact_id": f"explicit-{index}",
                    "category": "personal_context",
                    "content": f"用户明确指定记住第{index}条非常重要的信息",
                    "confidence": 0.99,
                    "salience": 0.9,
                }
                for index in range(1, 9)
            )
            context = self.service.build_session_context(
                person_id="employee:1",
                memory_read_allowed=True,
            )
        finally:
            original.PERSON_MEMORY_CONTEXT_MAX_CHARS = previous

        for index in range(1, 9):
            self.assertIn(f"第{index}条", context)

    def test_session_context_loads_a_bounded_snapshot_without_query_embedding(self) -> None:
        context = self.service.build_session_context(
            person_id="employee:1",
            memory_read_allowed=True,
        )

        self.assertIn("普通长期记忆", context)
        self.assertIn("美式咖啡", context)
        self.assertIn("明确要求记住", context)
        self.assertEqual(len(self.repository.retrieve_calls), 1)
        call = self.repository.retrieve_calls[0]
        self.assertEqual(call["query"], "")
        self.assertIsNone(call["query_embedding"])
        self.assertEqual(call["top_k"], PERSON_MEMORY_SESSION_TOP_K)

    def test_session_context_sanitizes_daily_summary_for_prompt(self) -> None:
        self.repository.daily_summaries = (
            {
                "summary_date": "2026-07-22",
                "content": "用户聊了签退时间和对话回忆。",
            },
        )

        context = self.service.build_session_context(
            person_id="employee:1",
            memory_read_allowed=True,
        )

        self.assertIn("签退时间和对话回忆", context)
        self.assertNotIn("用户聊了", context)

    def test_daily_conversation_recall_prefers_summary(self) -> None:
        self.repository.daily_summary_by_date["2026-07-22"] = {
            "content": "昨天主要测试了数字人的产品介绍和身份记忆。",
            "source_turn_count": 4,
        }
        self.repository.daily_turns = (
            {"user_text": "这条轮次只做兜底", "assistant_text": "好的"},
        )

        recall = self.service.recall_daily_conversation(
            person_id="employee:1",
            memory_read_allowed=True,
            target_date="2026-07-22",
            target_label="昨天",
        )

        self.assertIn("产品介绍", recall["summary"])
        self.assertEqual(recall["source_turn_count"], 4)
        self.assertEqual(len(recall["turns"]), 1)

    def test_daily_conversation_recall_falls_back_to_turns(self) -> None:
        self.repository.daily_turns = (
            {"user_text": "你的名字是什么？", "assistant_text": "我叫叮当。"},
            {"user_text": "介绍一下产品。", "assistant_text": "我们做数字人。"},
        )

        recall = self.service.recall_daily_conversation(
            person_id="employee:1",
            memory_read_allowed=True,
            target_date="2026-07-22",
            target_label="昨天",
        )

        self.assertEqual(recall["summary"], "")
        self.assertEqual(recall["source_turn_count"], 2)
        self.assertEqual(recall["turns"][1]["user_text"], "介绍一下产品。")

    def test_query_context_uses_retrieval_top_k_without_storage_cap(self) -> None:
        self.service.build_context(
            person_id="employee:1",
            query="我喜欢喝什么",
            memory_read_allowed=True,
        )

        call = self.repository.retrieve_calls[-1]
        self.assertEqual(call["top_k"], PERSON_MEMORY_RETRIEVAL_TOP_K)

    def test_repository_does_not_supersede_overflow_facts(self) -> None:
        source = inspect.getsource(PostgresPersonMemoryRepository.apply_extraction)

        self.assertNotIn("OFFSET", source)
        self.assertNotIn("status = 'superseded'", source)

    def test_migration_restores_previously_superseded_facts(self) -> None:
        versions = {version: "\n".join(statements) for version, statements in _migration_statements()}

        self.assertIn(4, versions)
        self.assertIn("WHERE status = 'superseded'", versions[4])
        self.assertIn("SET status = 'active'", versions[4])

    def test_migration_adds_daily_summary_table(self) -> None:
        versions = {version: "\n".join(statements) for version, statements in _migration_statements()}

        self.assertIn(5, versions)
        self.assertIn("person_memory_daily_summaries", versions[5])
        self.assertIn("embedding vector", versions[5])

    def test_process_due_daily_summaries_embeds_and_upserts_summary(self) -> None:
        self.repository.daily_candidates = (
            DailySummaryCandidate(
                person_id="tenant:tenant-a:employee:1",
                tenant_id="tenant-a",
                summary_date="2026-07-19",
                turn_count=2,
            ),
        )
        self.repository.daily_turns = (
            {
                "turn_id": "turn-1",
                "sequence_no": 1,
                "user_text": "今天客户演示要直接给结论",
                "assistant_text": "好的，我会简洁说明。",
                "created_at": "2026-07-19T10:00:00+08:00",
            },
        )

        result = self.service.process_due_daily_summaries(limit=1)

        self.assertEqual(len(result), 1)
        self.assertTrue(result[0]["embedding"])
        upsert_call = self.repository.daily_summary_calls[-1]
        self.assertEqual(upsert_call["summary_date"], "2026-07-19")
        self.assertEqual(upsert_call["embedding"], [0.1, 0.2])

    def test_empty_daily_summary_is_marked_to_avoid_repeated_agent_calls(self) -> None:
        self.repository.daily_candidates = (
            DailySummaryCandidate(
                person_id="tenant:tenant-a:employee:1",
                tenant_id="tenant-a",
                summary_date="2026-07-18",
                turn_count=1,
            ),
        )
        self.repository.daily_turns = (
            {
                "turn_id": "turn-1",
                "sequence_no": 1,
                "user_text": "你好",
                "assistant_text": "你好呀",
                "created_at": "2026-07-18T10:00:00+08:00",
            },
        )
        self.service.extractor.daily_summary = ""

        result = self.service.process_due_daily_summaries(limit=1)

        self.assertEqual(result, [])
        self.assertEqual(len(self.repository.skipped_daily_summaries), 1)
        self.assertEqual(
            self.repository.skipped_daily_summaries[0]["summary_date"],
            "2026-07-18",
        )

    def test_upsert_arrival_speech_task_delegates_to_repository(self) -> None:
        result = self.service.upsert_arrival_speech_task(
            tenant_id="computer-mine",
            creator_person_id="tenant:computer-mine:employee:1",
            creator_name="小羊",
            target_person_id="tenant:computer-mine:employee:2",
            target_name="小王",
            content="  准备会议  ",
            exact_text=False,
            repeat=True,
            actor="voice-command",
        )

        self.assertEqual(result["content"], "准备会议")
        self.assertEqual(result["targetName"], "小王")
        self.assertFalse(result["exactText"])
        self.assertTrue(result["repeat"])
        self.assertEqual(len(self.repository.arrival_task_calls), 1)

    def test_cancel_arrival_speech_task_delegates_to_repository(self) -> None:
        result = self.service.cancel_arrival_speech_tasks(
            tenant_id="computer-mine",
            creator_person_id="tenant:computer-mine:employee:1",
            target_person_id="tenant:computer-mine:employee:1",
            latest_only=False,
            actor="voice-command",
        )

        self.assertEqual(result["cancelled"], 1)
        self.assertEqual(len(self.repository.cancel_arrival_task_calls), 1)
        call = self.repository.cancel_arrival_task_calls[0]
        self.assertEqual(call["target_person_id"], "tenant:computer-mine:employee:1")
        self.assertFalse(call["latest_only"])


if __name__ == "__main__":
    unittest.main()

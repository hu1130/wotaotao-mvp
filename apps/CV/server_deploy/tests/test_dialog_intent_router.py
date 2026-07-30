from __future__ import annotations

import unittest
from types import SimpleNamespace

from core.dialog_intent_router import (
    DialogIntentRouter,
    INTENT_CHAT,
    INTENT_COMPANY,
    INTENT_PERSONAL,
    parse_conversation_recall_intent,
    is_assistant_identity_query,
    is_conversation_recall_query,
    is_personal_context_query,
    is_self_identity_query,
)


class DialogIntentRouterTests(unittest.TestCase):
    def test_person_identity_questions_are_chat_without_knowledge_probe(self) -> None:
        def unexpected_factory():
            raise AssertionError("identity chat must not access the knowledge base")

        router = DialogIntentRouter(knowledge_service_factory=unexpected_factory)

        for query in (
            "我是谁？",
            "你知道我是谁吗？",
            "你认识我吗？",
            "你还记得我是谁吗？",
            "我叫什么名字？",
        ):
            with self.subTest(query=query):
                route = router.route(query)
                self.assertFalse(route.use_knowledge)
                self.assertEqual(route.intent, INTENT_PERSONAL)
                self.assertEqual(route.reason, "keyword_personal_context")

    def test_short_rejection_is_chat_without_knowledge_probe(self) -> None:
        def unexpected_factory():
            raise AssertionError("short conversational reply must not probe knowledge")

        route = DialogIntentRouter(
            knowledge_service_factory=unexpected_factory
        ).route("不想了解。")

        self.assertFalse(route.use_knowledge)
        self.assertEqual(route.intent, INTENT_CHAT)
        self.assertEqual(route.reason, "keyword_obvious_chat")

    def test_assistant_identity_and_abuse_are_chat_without_knowledge_probe(self) -> None:
        def unexpected_factory():
            raise AssertionError("obvious chat must not probe knowledge")

        router = DialogIntentRouter(knowledge_service_factory=unexpected_factory)

        for query in (
            "你是哪个？",
            "你是哪位？",
            "你叫啥？",
            "你的名字是什么？",
            "你这个数字人叫什么名字？",
            "神经病吧？",
        ):
            with self.subTest(query=query):
                route = router.route(query)
                self.assertFalse(route.use_knowledge)
                self.assertEqual(route.intent, INTENT_CHAT)
                self.assertIn(route.reason, {"keyword_obvious_chat", "keyword_assistant_identity"})

    def test_assistant_identity_query_is_chat_intent(self) -> None:
        self.assertTrue(is_assistant_identity_query("你叫啥？"))
        self.assertTrue(is_assistant_identity_query("你的名字是什么？"))
        self.assertTrue(is_assistant_identity_query("你这个数字人叫什么名字？"))

    def test_assistant_identity_with_event_word_is_not_recall(self) -> None:
        query = "我问你是谁？"
        intent = parse_conversation_recall_intent(query)

        self.assertTrue(is_assistant_identity_query(query))
        self.assertFalse(intent.matched)
        self.assertFalse(intent.needs_clarification)
        self.assertFalse(is_conversation_recall_query(query))

    def test_incomplete_asr_fragment_is_chat_without_knowledge_probe(self) -> None:
        def unexpected_factory():
            raise AssertionError("incomplete ASR must not probe knowledge")

        router = DialogIntentRouter(knowledge_service_factory=unexpected_factory)

        for query in (
            "你，你是公司的。",
            "我刚才想问的是",
            "公司的产品和",
        ):
            with self.subTest(query=query):
                route = router.route(query)
                self.assertFalse(route.use_knowledge)
                self.assertEqual(route.reason, "incomplete_query")
                self.assertEqual(route.intent, INTENT_CHAT)

    def test_conversation_recall_is_chat_without_knowledge_probe(self) -> None:
        def unexpected_factory():
            raise AssertionError("conversation recall must not probe knowledge")

        router = DialogIntentRouter(knowledge_service_factory=unexpected_factory)

        for query in (
            "你记得我上次跟你说的啥吗？",
            "我上次跟你说了什么？",
            "刚才我问你啥了？",
            "我们之前聊了什么？",
            "你还记得刚才我们聊了什么吗？",
            "你说了什么？",
            "你刚才说了什么？",
            "你知道我刚刚跟你说了什么吗？",
            "我刚刚问了什么？",
        ):
            with self.subTest(query=query):
                route = router.route(query)
                self.assertFalse(route.use_knowledge)
                self.assertEqual(route.intent, INTENT_PERSONAL)
                self.assertEqual(route.reason, "keyword_personal_context")
                self.assertTrue(is_conversation_recall_query(query))

    def test_conversation_recall_intent_parses_date_and_target_slots(self) -> None:
        intent = parse_conversation_recall_intent("那你现在记得昨天我们聊了什么吗？")

        self.assertTrue(intent.matched)
        self.assertFalse(intent.needs_clarification)
        self.assertEqual(intent.time_scope, "yesterday")
        self.assertEqual(intent.day_offset, -1)
        self.assertEqual(intent.target_role, "user")

    def test_conversation_recall_intent_accepts_asr_noise(self) -> None:
        intent = parse_conversation_recall_intent("继昨天我们说过啥吗？")

        self.assertTrue(intent.matched)
        self.assertEqual(intent.day_offset, -1)
        self.assertTrue(is_conversation_recall_query("继昨天我们说过啥吗？"))

    def test_conversation_recall_statement_needs_clarification(self) -> None:
        intent = parse_conversation_recall_intent("昨天我们聊了很多。")

        self.assertFalse(intent.matched)
        self.assertTrue(intent.needs_clarification)
        self.assertEqual(intent.day_offset, -1)

    def test_non_recall_date_statement_is_not_personal(self) -> None:
        intent = parse_conversation_recall_intent("昨天公司的产品很多。")

        self.assertFalse(intent.matched)
        self.assertFalse(intent.needs_clarification)

    def test_assistant_conversation_recall_target_is_structured(self) -> None:
        intent = parse_conversation_recall_intent("你刚才说了什么？")

        self.assertTrue(intent.matched)
        self.assertEqual(intent.time_scope, "just_now")
        self.assertEqual(intent.target_role, "assistant")

    def test_hearing_clarification_is_not_conversation_recall(self) -> None:
        for query in (
            "我听不清你说什么。",
            "刚才没听清你说什么。",
            "我没有听懂你说什么。",
        ):
            with self.subTest(query=query):
                intent = parse_conversation_recall_intent(query)
                self.assertFalse(intent.matched)
                self.assertFalse(intent.needs_clarification)
                self.assertFalse(is_conversation_recall_query(query))

    def test_personal_context_questions_are_chat_without_knowledge_probe(self) -> None:
        def unexpected_factory():
            raise AssertionError("personal memory intent must not access company knowledge")

        router = DialogIntentRouter(knowledge_service_factory=unexpected_factory)

        for query in (
            "你记住了我什么？",
            "我喜欢喝什么？",
            "我的偏好是什么？",
            "你知道我的习惯吗？",
            "关于我你记得哪些信息？",
            "我让你记住了什么？",
        ):
            with self.subTest(query=query):
                route = router.route(query)
                self.assertFalse(route.use_knowledge)
                self.assertEqual(route.intent, INTENT_PERSONAL)
                self.assertEqual(route.reason, "keyword_personal_context")
                self.assertTrue(is_personal_context_query(query))

    def test_company_product_question_uses_knowledge(self) -> None:
        calls: list[tuple[str, int, float]] = []

        class KnowledgeService:
            def search(self, query: str, *, top_k: int, min_score: float):
                calls.append((query, top_k, min_score))
                return [SimpleNamespace(score=0.81)]

        router = DialogIntentRouter(
            knowledge_service_factory=KnowledgeService,
            min_score=0.2,
            probe_top_k=4,
        )

        route = router.route("你们公司的产品是什么？")

        self.assertTrue(route.use_knowledge)
        self.assertEqual(route.intent, INTENT_COMPANY)
        self.assertEqual(route.reason, "keyword_company_scope_knowledge_probe_hit")
        self.assertEqual(calls, [("你们公司的产品是什么？", 4, 0.2)])

    def test_company_owner_question_is_not_person_identity(self) -> None:
        self.assertFalse(is_self_identity_query("公司负责人是谁？"))
        self.assertFalse(is_self_identity_query("你是谁？"))

    def test_company_scoped_memory_word_still_uses_knowledge(self) -> None:
        calls: list[tuple[str, int, float]] = []

        class KnowledgeService:
            def search(self, query: str, *, top_k: int, min_score: float):
                calls.append((query, top_k, min_score))
                return [SimpleNamespace(score=0.72)]

        router = DialogIntentRouter(knowledge_service_factory=KnowledgeService)

        route = router.route("公司让我记住的业务流程是什么？")

        self.assertTrue(route.use_knowledge)
        self.assertEqual(route.intent, INTENT_COMPANY)
        self.assertEqual(route.reason, "keyword_company_scope_knowledge_probe_hit")
        self.assertFalse(is_personal_context_query("公司让我记住的业务流程是什么？"))
        self.assertEqual(len(calls), 1)

    def test_product_document_terms_are_company_keywords(self) -> None:
        calls: list[str] = []

        class KnowledgeService:
            def search(self, query: str, *, top_k: int, min_score: float):
                calls.append(query)
                return [SimpleNamespace(score=0.74)]

        router = DialogIntentRouter(knowledge_service_factory=KnowledgeService)

        for query in (
            "数字人前台怎么介绍？",
            "AI口播的营销话术有哪些？",
            "视频生成产品和竞品有什么区别？",
            "一键换衣客户常问问题是什么？",
            "AI人事系统产品介绍一下",
            "超级员工外贸版适合什么客户？",
            "深度觉醒公司介绍",
            "面试流程是什么？",
        ):
            with self.subTest(query=query):
                route = router.route(query)
                self.assertTrue(route.use_knowledge)
                self.assertEqual(route.intent, INTENT_COMPANY)
                self.assertTrue(route.reason.startswith("keyword_company_scope"))

        self.assertEqual(calls, [
            "数字人前台怎么介绍？",
            "AI口播的营销话术有哪些？",
            "视频生成产品和竞品有什么区别？",
            "一键换衣客户常问问题是什么？",
            "AI人事系统产品介绍一下",
            "超级员工外贸版适合什么客户？",
            "深度觉醒公司介绍",
            "面试流程是什么？",
        ])

    def test_plain_eating_chat_is_not_company_keyword(self) -> None:
        def unexpected_factory():
            raise AssertionError("plain eating chat must not be a company keyword")

        router = DialogIntentRouter(
            knowledge_service_factory=unexpected_factory,
            intent_embedding_enabled=False,
            probe_knowledge=False,
        )

        route = router.route("我想吃饭")

        self.assertTrue(route.use_knowledge)
        self.assertEqual(route.intent, INTENT_COMPANY)
        self.assertEqual(route.reason, "default_company_intent")

    def test_embedding_personal_intent_is_chat(self) -> None:
        def unexpected_factory():
            raise AssertionError("embedding personal intent must not search knowledge")

        router = DialogIntentRouter(
            knowledge_service_factory=unexpected_factory,
            intent_embedding_factory=lambda: FakeIntentEmbedding("personal"),
            intent_embedding_min_score=0.8,
        )

        route = router.route("你了解我的饮品选择吗？")

        self.assertFalse(route.use_knowledge)
        self.assertEqual(route.intent, INTENT_PERSONAL)
        self.assertTrue(route.reason.startswith("embedding_personal_intent:"))

    def test_embedding_chat_intent_is_chat(self) -> None:
        def unexpected_factory():
            raise AssertionError("embedding chat intent must not search knowledge")

        router = DialogIntentRouter(
            knowledge_service_factory=unexpected_factory,
            intent_embedding_factory=lambda: FakeIntentEmbedding("chat"),
            intent_embedding_min_score=0.8,
        )

        route = router.route("最近还好吗？")

        self.assertFalse(route.use_knowledge)
        self.assertEqual(route.intent, INTENT_CHAT)
        self.assertTrue(route.reason.startswith("embedding_chat_intent:"))

    def test_embedding_company_intent_uses_knowledge(self) -> None:
        calls: list[str] = []

        class KnowledgeService:
            def search(self, query: str, *, top_k: int, min_score: float):
                calls.append(query)
                return [SimpleNamespace(score=0.76)]

        router = DialogIntentRouter(
            knowledge_service_factory=KnowledgeService,
            intent_embedding_factory=lambda: FakeIntentEmbedding("company"),
            intent_embedding_min_score=0.8,
        )

        route = router.route("能讲讲服务范围吗？")

        self.assertTrue(route.use_knowledge)
        self.assertEqual(route.intent, INTENT_COMPANY)
        self.assertTrue(route.reason.startswith("embedding_company_intent:"))
        self.assertEqual(calls, ["能讲讲服务范围吗？"])

    def test_embedding_low_score_defaults_to_company_knowledge(self) -> None:
        calls: list[tuple[str, float]] = []

        class KnowledgeService:
            def search(self, query: str, *, top_k: int, min_score: float):
                calls.append((query, min_score))
                return []

        router = DialogIntentRouter(
            knowledge_service_factory=KnowledgeService,
            intent_embedding_factory=lambda: FakeIntentEmbedding("unknown"),
            intent_embedding_min_score=0.8,
            default_company_min_score=0.35,
        )

        route = router.route("这句话和样本都不像")

        self.assertTrue(route.use_knowledge)
        self.assertEqual(route.intent, INTENT_COMPANY)
        self.assertEqual(route.reason, "default_company_intent_knowledge_probe_miss")
        self.assertEqual(route.knowledge_min_score, 0.35)
        self.assertEqual(calls, [("这句话和样本都不像", 0.35)])

    def test_default_company_low_score_does_not_probe_hit(self) -> None:
        calls: list[tuple[str, float]] = []

        class KnowledgeService:
            def search(self, query: str, *, top_k: int, min_score: float):
                calls.append((query, min_score))
                if min_score <= 0.25:
                    return [SimpleNamespace(score=0.248)]
                return []

        router = DialogIntentRouter(
            knowledge_service_factory=KnowledgeService,
            intent_embedding_factory=lambda: FakeIntentEmbedding("unknown"),
            intent_embedding_min_score=0.8,
            min_score=0.12,
            default_company_min_score=0.35,
        )

        route = router.route("这句不明确的问题")

        self.assertTrue(route.use_knowledge)
        self.assertEqual(route.intent, INTENT_COMPANY)
        self.assertEqual(route.reason, "default_company_intent_knowledge_probe_miss")
        self.assertEqual(route.results, [])
        self.assertEqual(calls, [("这句不明确的问题", 0.35)])


class FakeIntentEmbedding:
    api_base = "test"
    dimension = 3

    def __init__(self, query_intent: str):
        self.query_intent = query_intent
        self.model = f"intent-test-{query_intent}"

    def embed_query(self, text: str) -> list[float]:
        return self._query_vector()

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self._example_vector(text) for text in texts]

    def _query_vector(self) -> list[float]:
        if self.query_intent == "chat":
            return [1.0, 0.0, 0.0]
        if self.query_intent == "personal":
            return [0.0, 1.0, 0.0]
        if self.query_intent == "company":
            return [0.0, 0.0, 1.0]
        return [0.1, 0.1, 0.1]

    def _example_vector(self, text: str) -> list[float]:
        if any(token in text for token in ("记住", "喜欢", "偏好", "习惯", "我是谁", "聊了什么")):
            return [0.0, 1.0, 0.0]
        if any(
            token in text
            for token in (
                "公司",
                "业务",
                "产品",
                "制度",
                "考勤",
                "客户",
                "项目",
                "企业",
                "数字人",
                "口播",
                "视频生成",
                "一键换衣",
                "营销",
                "人事",
                "超级员工",
            )
        ):
            return [0.0, 0.0, 1.0]
        return [1.0, 0.0, 0.0]


if __name__ == "__main__":
    unittest.main()

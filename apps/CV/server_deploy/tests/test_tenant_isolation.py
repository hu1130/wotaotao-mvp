from __future__ import annotations

import time
import unittest
from pathlib import Path

from api.auth import TenantCredentialRegistry, sign_request
from api.voice_auth import VoiceTicketStore
from config import KNOWLEDGE_BASE_DIR
from core.client_tasks import ClientTaskQueue
from core.dialog_actions import (
    ACTION_ADJUST_VOLUME,
    DialogActionExecutor,
    DialogActionProposal,
)
from core.events import EventBus
from core.knowledge.service import KnowledgeService
from core.redis_checkin import RedisCheckIn
from core.tenant import subject_belongs_to_tenant, tenant_subject_id
from core.unknown_visitors import UnknownVisitorStore


class OfflineHealth:
    client = None

    @staticmethod
    def ensure_connected() -> bool:
        return False


class OnlineHealth:
    client = object()

    @staticmethod
    def ensure_connected() -> bool:
        return True


class SignalRecorder:
    def __init__(self) -> None:
        self.signals: list[dict] = []

    def publish(self, signal: dict) -> None:
        self.signals.append(signal)


class TenantIsolationTests(unittest.TestCase):
    def test_hmac_api_key_resolves_exactly_one_trusted_tenant(self) -> None:
        registry = TenantCredentialRegistry.from_mapping(
            {
                "tenant-a-key": {"tenant_id": "tenant-a", "secret": "secret-a"},
                "tenant-b-key": {"tenant_id": "tenant-b", "secret": "secret-b"},
            }
        )
        timestamp = str(int(time.time()))
        body = b'{"tenant_id":"tenant-b"}'
        signature = sign_request(
            "secret-a", "POST", "/api/v1/recognition/frame", timestamp, body
        )

        context = registry.authenticate(
            method="POST",
            path="/api/v1/recognition/frame",
            timestamp=timestamp,
            body=body,
            api_key="tenant-a-key",
            signature=signature,
            tolerance_seconds=60,
        )

        self.assertIsNotNone(context)
        self.assertEqual(context.tenant_id, "tenant-a")
        self.assertIsNone(
            registry.authenticate(
                method="POST",
                path="/api/v1/recognition/frame",
                timestamp=timestamp,
                body=body,
                api_key="tenant-b-key",
                signature=signature,
                tolerance_seconds=60,
            )
        )

        with self.assertRaisesRegex(RuntimeError, "tenant_id"):
            TenantCredentialRegistry.from_mapping(
                {"invalid-key": {"secret": "secret-without-tenant"}}
            )

    def test_client_tasks_cannot_be_claimed_or_completed_cross_tenant(self) -> None:
        queue = ClientTaskQueue()
        task_a = queue.create("capture", tenant_id="tenant-a")
        task_b = queue.create("capture", tenant_id="tenant-b")

        self.assertEqual(queue.claim_next(tenant_id="tenant-a").id, task_a.id)
        self.assertIsNone(queue.get(task_a.id, tenant_id="tenant-b"))
        self.assertIsNone(
            queue.complete(task_a.id, ok=True, tenant_id="tenant-b")
        )
        self.assertEqual(queue.claim_next(tenant_id="tenant-b").id, task_b.id)

    def test_voice_ticket_is_device_bound_and_one_time(self) -> None:
        store = VoiceTicketStore(OfflineHealth())
        token, binding = store.issue("tenant-a", "frontdesk-a")

        self.assertEqual(binding.tenant_id, "tenant-a")
        self.assertIsNone(store.consume(token, "frontdesk-b"))
        self.assertIsNone(store.consume(token, "frontdesk-a"))

        token, _ = store.issue("tenant-a", "frontdesk-a")
        consumed = store.consume(token, "frontdesk-a")
        self.assertEqual(consumed.tenant_id, "tenant-a")
        self.assertIsNone(store.consume(token, "frontdesk-a"))

    def test_dialog_action_signal_keeps_call_tenant_without_shared_state(self) -> None:
        recorder = SignalRecorder()
        executor = DialogActionExecutor(signal_bus=recorder)
        proposal = DialogActionProposal(
            action=ACTION_ADJUST_VOLUME,
            confidence=1.0,
            params={"direction": "increase"},
        )

        result_a = executor.execute(
            proposal,
            user_text="大一点",
            conversation_id="conversation-a",
            tenant_id="tenant-a",
        )
        result_b = executor.execute(
            proposal,
            user_text="大一点",
            conversation_id="conversation-b",
            tenant_id="tenant-b",
        )

        self.assertEqual(result_a.agent_signal["tenant_id"], "tenant-a")
        self.assertEqual(result_b.agent_signal["tenant_id"], "tenant-b")

    def test_redis_local_fallback_is_tenant_scoped(self) -> None:
        store = RedisCheckIn.__new__(RedisCheckIn)
        store.tenant_id = "tenant-a"
        store._health = OfflineHealth()
        store._local_date = store._today()
        store._local_checked_in = set()
        store._local_checked_out = set()
        store._local_cooldowns = {}

        store.mark_checked_in("同名员工", tenant_id="tenant-a")

        self.assertTrue(store.is_checked_in_today("同名员工", tenant_id="tenant-a"))
        self.assertFalse(store.is_checked_in_today("同名员工", tenant_id="tenant-b"))
        self.assertIn("tenant-a", store._today_key("同名员工", "tenant-a"))

    def test_event_topic_uses_tenant_namespace(self) -> None:
        bus = EventBus.__new__(EventBus)
        bus.tenant_id = "tenant-a"
        bus._health = OnlineHealth()
        bus._emotion_module = None
        bus._last_avatar_event = None
        bus._last_avatar_time = 0.0
        captured: list[str] = []
        bus._do_publish = lambda topic, message, payload: captured.append(topic)

        bus.publish("checkin", {"name": "员工"})

        self.assertEqual(len(captured), 1)
        self.assertIn(".tenant-a.checkin", captured[0])

        bus.checkin("员工", 1, 0.9)
        self.assertIn(".tenant-a.checkin", captured[1])

    def test_person_subject_id_is_not_reusable_by_another_tenant(self) -> None:
        subject = tenant_subject_id("tenant-a", "employee-uuid")

        self.assertTrue(subject_belongs_to_tenant(subject, "tenant-a"))
        self.assertFalse(subject_belongs_to_tenant(subject, "tenant-b"))

    def test_unknown_visitor_biometrics_use_tenant_specific_files(self) -> None:
        default_store = UnknownVisitorStore(path="cache/unknown.json", tenant_id="default")
        tenant_store = UnknownVisitorStore(path="cache/unknown.json", tenant_id="tenant-a")

        self.assertEqual(default_store.path, "cache/unknown.json")
        self.assertTrue(
            tenant_store.path.endswith("tenants\\tenant-a\\unknown.json")
            or tenant_store.path.endswith("tenants/tenant-a/unknown.json")
        )

    def test_default_knowledge_index_excludes_other_tenant_directories(self) -> None:
        service = KnowledgeService.__new__(KnowledgeService)
        service.tenant_id = "default"
        base = Path(KNOWLEDGE_BASE_DIR).resolve()

        self.assertTrue(service._document_allowed(str(base / "company.md")))
        self.assertFalse(
            service._document_allowed(str(base / "tenants" / "tenant-b" / "private.md"))
        )


if __name__ == "__main__":
    unittest.main()

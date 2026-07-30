from __future__ import annotations

import asyncio
import unittest
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from core.concurrency import AsyncCapacityGate, CapacityExceeded
from core.person_sessions.manager import PersonConversationManager
from core.recognition_cache import RecognitionCache
from core.runtime_scope import RuntimeScope
from core.vote import VoteBuffer


class FakeMemory:
    def start_conversation(self, **kwargs) -> None:
        return

    def append_turn(self, **kwargs) -> None:
        return

    def recent_context(self, person_id: str, *, limit: int = 6) -> list[dict]:
        return []

    def end_conversation(self, conversation_id: str, *, reason: str) -> None:
        return

    def close(self) -> None:
        return


def recognized_face(person_id: str, name: str) -> dict:
    return {
        "person_id": person_id,
        "name": name,
        "recognized": True,
        "track_id": 1,
        "similarity": 0.9,
        "bbox": [100, 100, 300, 350],
    }


class RuntimeIsolationTests(unittest.TestCase):
    def test_vote_buffer_isolates_identical_track_ids_by_scope(self) -> None:
        votes = VoteBuffer(window=3, min_votes=2, cooldown=5)

        self.assertIsNone(votes.vote(1, "甲", 0.9, 1.0, scope_key="device-a"))
        self.assertIsNone(votes.vote(1, "乙", 0.9, 1.0, scope_key="device-b"))
        self.assertEqual(
            votes.vote(1, "甲", 0.9, 1.1, scope_key="device-a"),
            "甲",
        )
        self.assertEqual(
            votes.vote(1, "乙", 0.9, 1.1, scope_key="device-b"),
            "乙",
        )

    def test_recognition_cache_isolates_identical_track_ids_by_scope(self) -> None:
        cache = RecognitionCache()
        embedding = np.asarray([1.0, 0.0], dtype=np.float32)
        cache.set_known(1, "甲", 0.91, embedding, scope_key="device-a")
        cache.set_known(1, "乙", 0.92, embedding, scope_key="device-b")

        self.assertEqual(cache.get_known(1, scope_key="device-a")[0], "甲")
        self.assertEqual(cache.get_known(1, scope_key="device-b")[0], "乙")
        cache.cleanup(set(), scope_key="device-a")
        self.assertIsNone(cache.get_known(1, scope_key="device-a")[0])
        self.assertEqual(cache.get_known(1, scope_key="device-b")[0], "乙")

    def test_same_device_id_is_isolated_across_tenants(self) -> None:
        manager = PersonConversationManager(FakeMemory(), acquire_seconds=0.0)
        tenant_a = manager.observe(
            "frontdesk",
            [recognized_face("employee:a", "甲")],
            tenant_id="tenant-a",
            frame_width=1280,
            frame_height=720,
            now=10.0,
        )
        tenant_b = manager.observe(
            "frontdesk",
            [recognized_face("employee:b", "乙")],
            tenant_id="tenant-b",
            frame_width=1280,
            frame_height=720,
            now=10.0,
        )

        self.assertEqual(tenant_a.owner_id, "employee:a")
        self.assertEqual(tenant_b.owner_id, "employee:b")
        self.assertNotEqual(tenant_a.conversation_id, tenant_b.conversation_id)
        self.assertEqual(
            manager.get("frontdesk", tenant_id="tenant-a").owner_id,
            "employee:a",
        )

    def test_parallel_devices_keep_independent_sessions(self) -> None:
        manager = PersonConversationManager(FakeMemory(), acquire_seconds=0.0)

        def observe(index: int) -> str:
            snapshot = manager.observe(
                f"device-{index}",
                [recognized_face(f"employee:{index}", f"员工{index}")],
                tenant_id="tenant-a",
                frame_width=1280,
                frame_height=720,
                now=10.0,
            )
            return snapshot.owner_id

        with ThreadPoolExecutor(max_workers=8) as executor:
            owners = list(executor.map(observe, range(32)))

        self.assertEqual(owners, [f"employee:{index}" for index in range(32)])

    def test_runtime_scope_normalizes_untrusted_parts(self) -> None:
        scope = RuntimeScope.build(" tenant/甲 ", " front desk/01 ")
        self.assertNotIn("/", scope.key)
        self.assertEqual(scope.device_id, "front-desk-01")


class CapacityGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_gate_rejects_when_capacity_timeout_expires(self) -> None:
        gate = AsyncCapacityGate("test", limit=1, timeout_seconds=0.01)
        entered = asyncio.Event()
        release = asyncio.Event()

        async def holder() -> None:
            async with gate.slot("scope-a"):
                entered.set()
                await release.wait()

        task = asyncio.create_task(holder())
        await entered.wait()
        with self.assertRaises(CapacityExceeded):
            async with gate.slot("scope-b"):
                pass
        release.set()
        await task
        self.assertEqual(gate.snapshot()["rejected"], 1)


if __name__ == "__main__":
    unittest.main()

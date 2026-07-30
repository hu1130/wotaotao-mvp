from __future__ import annotations

import unittest

from core.client_task_worker import ClientTaskWorker


class FakeClient:
    pass


class ClientTaskWorkerTests(unittest.TestCase):
    def test_face_capture_requires_name_from_task_payload(self) -> None:
        worker = ClientTaskWorker(client=FakeClient(), device_id="dev-test")

        with self.assertRaisesRegex(RuntimeError, "缺少员工姓名"):
            worker._run_face_capture({})


if __name__ == "__main__":
    unittest.main()

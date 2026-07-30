from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from core.hrms_attendance_sync import HrmsAttendanceSyncer


class HrmsAttendanceSyncTests(unittest.TestCase):
    def test_disabled_sync_does_not_read_or_enqueue(self):
        syncer = HrmsAttendanceSyncer()
        db = Mock()

        with patch("core.hrms_attendance_sync.HRMS_ATTENDANCE_SYNC_ENABLED", False):
            syncer.enqueue_check_in(db, tenant_id="tenant-a", name="Alice", row_id=1)

        db.get_attendance_record.assert_not_called()
        db.enqueue_hrms_attendance_sync.assert_not_called()

    def test_enqueue_check_in_builds_deduplicated_payload(self):
        syncer = HrmsAttendanceSyncer()
        db = Mock()
        db.get_attendance_record.return_value = {
            "id": 7,
            "tenant_id": "tenant-a",
            "name": "小游",
            "date": "2026-07-23",
            "check_in": "09:01:02",
            "check_out": None,
            "duration": None,
        }
        db.enqueue_hrms_attendance_sync.return_value = 11

        with (
            patch("core.hrms_attendance_sync.HRMS_ATTENDANCE_SYNC_ENABLED", True),
            patch("core.hrms_attendance_sync.HRMS_ATTENDANCE_BASE_URL", "https://hrms.example"),
            patch("core.hrms_attendance_sync.HRMS_ATTENDANCE_API_KEY", "key"),
            patch("core.hrms_attendance_sync.HRMS_ATTENDANCE_API_SECRET", "secret"),
            patch.object(syncer, "flush_pending") as flush_pending,
        ):
            syncer.enqueue_check_in(db, tenant_id="tenant-a", name="小游", row_id=7)

        payload = db.enqueue_hrms_attendance_sync.call_args.kwargs["payload"]
        self.assertEqual(payload["externalId"], "cv-tenant-a-7-check-in")
        self.assertEqual(payload["frontdeskNickname"], "小游")
        self.assertEqual(payload["action"], "check-in")
        self.assertEqual(payload["punchedAt"], "2026-07-23 09:01:02")
        flush_pending.assert_called_once_with(db, limit=1)

    def test_employee_mapping_uses_frontdesk_nickname(self):
        syncer = HrmsAttendanceSyncer()

        with patch.object(syncer, "_request_json", return_value={
            "employees": [
                {
                    "employeeId": "emp-1",
                    "name": "游总",
                    "frontdeskNickname": "小游",
                    "employeeNo": "A001",
                }
            ]
        }):
            payload = syncer._with_employee_id({"frontdeskNickname": "小游"})

        self.assertEqual(payload["employeeId"], "emp-1")

    def test_sync_employees_registers_hrms_frontdesk_name(self):
        syncer = HrmsAttendanceSyncer()
        mkdir = Mock()

        with (
            patch("core.hrms_attendance_sync.HRMS_FRONTDESK_EMPLOYEE_SYNC_ENABLED", True),
            patch("core.hrms_attendance_sync.HRMS_ATTENDANCE_BASE_URL", "https://hrms.example"),
            patch("core.hrms_attendance_sync.HRMS_ATTENDANCE_API_KEY", "key"),
            patch("core.hrms_attendance_sync.HRMS_ATTENDANCE_API_SECRET", "secret"),
            patch.object(syncer, "_request_json", return_value={
                "employees": [
                    {
                        "employeeId": "emp-1",
                        "name": "游总",
                        "frontdeskNickname": "小游",
                        "status": "在职",
                        "frontdesk": {"registered": True},
                    }
                ]
            }),
            patch("core.attendance_db.AttendanceDB") as attendance_db,
            patch("core.employee_names.tenant_employee_directory", return_value=mkdir),
        ):
            attendance_db.return_value.register_employee.return_value = True
            result = syncer.sync_employees_from_hrms()

        self.assertEqual(result["synced"], 1)
        attendance_db.return_value.register_employee.assert_called_once_with("小游", "default")
        mkdir.mkdir.assert_called_once()

    def test_poll_face_enroll_task_creates_client_task_with_hrms_metadata(self):
        syncer = HrmsAttendanceSyncer()
        queue = Mock()
        queue.create.return_value.id = "client-task-1"
        queue.create.return_value.target_device_id = ""

        with (
            patch("core.hrms_attendance_sync.HRMS_FRONTDESK_EMPLOYEE_SYNC_ENABLED", True),
            patch("core.hrms_attendance_sync.HRMS_ATTENDANCE_BASE_URL", "https://hrms.example"),
            patch("core.hrms_attendance_sync.HRMS_ATTENDANCE_API_KEY", "key"),
            patch("core.hrms_attendance_sync.HRMS_ATTENDANCE_API_SECRET", "secret"),
            patch.object(syncer, "_request_json", return_value={
                "tasks": [
                    {
                        "taskId": "hrms-task-1",
                        "type": "face.captureEnroll",
                        "employee": {
                            "employeeId": "emp-1",
                            "name": "游总",
                            "frontdeskNickname": "小游",
                            "status": "在职",
                            "frontdesk": {"registered": True},
                        },
                        "payload": {
                            "employeeId": "emp-1",
                            "name": "小游",
                            "frontdeskNickname": "小游",
                            "cameraIndex": 1,
                            "warmupFrames": 8,
                        },
                    }
                ]
            }),
            patch.object(syncer, "_register_hrms_employee", return_value={"synced": True}),
            patch("core.client_tasks.get_client_task_queue", return_value=queue),
        ):
            created = syncer.poll_face_enroll_tasks_from_hrms()

        self.assertEqual(created, 1)
        action, payload = queue.create.call_args.args[:2]
        self.assertEqual(action, "capture_face_enroll")
        self.assertEqual(payload["name"], "小游")
        self.assertEqual(payload["cameraIndex"], 1)
        self.assertEqual(payload["hrms"]["employeeId"], "emp-1")
        self.assertEqual(payload["hrms"]["taskId"], "hrms-task-1")

    def test_report_face_enroll_result_allows_device_input_name(self):
        syncer = HrmsAttendanceSyncer()
        task = {
            "id": "client-task-1",
            "status": "done",
            "payload": {
                "hrms": {
                    "tenantId": "computer-mine",
                    "deviceId": "dev-1",
                    "taskId": "hrms-task-1",
                    "nameSource": "device-input",
                }
            },
            "result": {
                "name": "小羊",
                "deviceId": "dev-1",
                "finishedAt": "2026-07-23 15:20:00",
            },
        }

        with patch.object(syncer, "_request_json", return_value={"ok": True}) as request_json:
            syncer.report_face_enroll_task_result(task)

        payload = request_json.call_args.args[2]
        self.assertEqual(payload["employeeId"], "")
        self.assertEqual(payload["tenantId"], "computer-mine")
        self.assertEqual(payload["frontdeskNickname"], "小羊")
        self.assertEqual(payload["clientTaskId"], "client-task-1")
        self.assertEqual(payload["taskId"], "hrms-task-1")


if __name__ == "__main__":
    unittest.main()

"""Push local frontdesk attendance records to the HRMS cloud frontdesk API."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any

from config import (
    HRMS_ATTENDANCE_API_KEY,
    HRMS_ATTENDANCE_API_SECRET,
    HRMS_ATTENDANCE_BASE_URL,
    HRMS_ATTENDANCE_DEVICE_ID,
    HRMS_ATTENDANCE_EMPLOYEE_CACHE_SECONDS,
    HRMS_ATTENDANCE_SYNC_BATCH_SIZE,
    HRMS_ATTENDANCE_SYNC_ENABLED,
    HRMS_ATTENDANCE_SYNC_RETRY_SECONDS,
    HRMS_ATTENDANCE_SYNC_TIMEOUT_SECONDS,
    HRMS_ATTENDANCE_SYNC_WORKER_INTERVAL_SECONDS,
    HRMS_FRONTDESK_EMPLOYEE_SYNC_ENABLED,
    HRMS_FRONTDESK_EMPLOYEE_SYNC_INTERVAL_SECONDS,
    HRMS_FRONTDESK_TASK_POLL_SECONDS,
    HRMS_FRONTDESK_TASK_TARGET_DEVICE_ID,
)
from core.tenant import DEFAULT_TENANT_ID, normalize_tenant_id

logger = logging.getLogger(__name__)


class HrmsAttendanceSyncer:
    def __init__(self) -> None:
        self._employee_cache: dict[str, str] = {}
        self._employee_cache_at = 0.0
        self._worker: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.RLock()
        self._last_employee_sync_at = 0.0
        self._claimed_hrms_task_ids: set[str] = set()

    @property
    def enabled(self) -> bool:
        return bool(HRMS_ATTENDANCE_SYNC_ENABLED and self._configured)

    @property
    def frontdesk_enabled(self) -> bool:
        return bool(
            HRMS_FRONTDESK_EMPLOYEE_SYNC_ENABLED
            and self._configured
        )

    @property
    def _configured(self) -> bool:
        return bool(
            HRMS_ATTENDANCE_BASE_URL
            and HRMS_ATTENDANCE_API_KEY
            and HRMS_ATTENDANCE_API_SECRET
        )

    def enqueue_check_in(
        self,
        attendance_db,
        *,
        tenant_id: str,
        name: str,
        row_id: int,
    ) -> None:
        if not self.enabled:
            logger.debug(
                "HRMS 考勤同步未启用: tenant=%s name=%s row=%s action=check-in",
                tenant_id,
                name,
                row_id,
            )
            return
        record = attendance_db.get_attendance_record(row_id)
        if not record:
            logger.warning(
                "HRMS 考勤同步跳过: tenant=%s name=%s row=%s reason=record_missing",
                tenant_id,
                name,
                row_id,
            )
            return
        self._enqueue_record(attendance_db, record, action="check-in", status="正常")

    def enqueue_check_out(
        self,
        attendance_db,
        *,
        tenant_id: str,
        name: str,
        row_id: int | None = None,
    ) -> None:
        if not self.enabled:
            logger.debug(
                "HRMS 考勤同步未启用: tenant=%s name=%s row=%s action=check-out",
                tenant_id,
                name,
                row_id or "",
            )
            return
        record = (
            attendance_db.get_attendance_record(row_id)
            if row_id
            else attendance_db.get_latest_today_record(name, tenant_id)
        )
        if not record:
            logger.warning(
                "HRMS 考勤同步跳过: tenant=%s name=%s row=%s reason=record_missing",
                tenant_id,
                name,
                row_id or "",
            )
            return
        self._enqueue_record(attendance_db, record, action="check-out", status="已签退")

    def _enqueue_record(
        self,
        attendance_db,
        record: dict[str, Any],
        *,
        action: str,
        status: str,
    ) -> None:
        payload = self._payload_from_record(record, action=action, status=status)
        outbox_id = attendance_db.enqueue_hrms_attendance_sync(
            tenant_id=str(record.get("tenant_id") or DEFAULT_TENANT_ID),
            attendance_row_id=int(record["id"]),
            action=action,
            payload=payload,
        )
        logger.info(
            "HRMS 考勤同步已入队: outbox=%s tenant=%s name=%s row=%s action=%s",
            outbox_id,
            record.get("tenant_id"),
            record.get("name"),
            record.get("id"),
            action,
        )
        self.flush_pending(attendance_db, limit=1)

    def flush_pending(self, attendance_db=None, *, limit: int | None = None) -> int:
        if not self.enabled:
            return 0
        if attendance_db is None:
            from core.attendance_db import AttendanceDB

            attendance_db = AttendanceDB()
        pending = attendance_db.list_pending_hrms_attendance_sync(
            limit or HRMS_ATTENDANCE_SYNC_BATCH_SIZE
        )
        pushed = 0
        for item in pending:
            try:
                payload = self._with_employee_id(dict(item["payload"]))
                response = self._request_json(
                    "POST",
                    "/api/cloud/frontdesk/attendance/push",
                    {"records": [payload]},
                )
                attendance_db.mark_hrms_attendance_sync_done(int(item["id"]))
                pushed += 1
                logger.info(
                    "HRMS 考勤同步成功: outbox=%s tenant=%s name=%s action=%s response=%s",
                    item["id"],
                    item["tenant_id"],
                    payload.get("frontdeskNickname") or payload.get("name"),
                    payload.get("action"),
                    _compact_response(response),
                )
            except Exception as exc:
                attendance_db.mark_hrms_attendance_sync_failed(
                    int(item["id"]),
                    str(exc),
                    HRMS_ATTENDANCE_SYNC_RETRY_SECONDS,
                )
                logger.warning(
                    "HRMS 考勤同步失败: outbox=%s tenant=%s action=%s attempts=%s error=%s",
                    item["id"],
                    item["tenant_id"],
                    item["action"],
                    item.get("attempts"),
                    exc,
                )
        return pushed

    def start_worker(self) -> None:
        if not self.enabled and not self.frontdesk_enabled:
            logger.info("HRMS 前台同步未启用，跳过后台线程")
            return
        with self._lock:
            if self._worker and self._worker.is_alive():
                return
            self._stop_event.clear()
            self._worker = threading.Thread(
                target=self._worker_loop,
                name="HrmsAttendanceSyncWorker",
                daemon=True,
            )
            self._worker.start()
        logger.info(
            "HRMS 前台同步后台线程已启动: baseUrl=%s device=%s attendance=%s employeeSync=%s attendanceInterval=%.1fs taskInterval=%.1fs employeeInterval=%.1fs",
            HRMS_ATTENDANCE_BASE_URL,
            HRMS_ATTENDANCE_DEVICE_ID,
            self.enabled,
            self.frontdesk_enabled,
            HRMS_ATTENDANCE_SYNC_WORKER_INTERVAL_SECONDS,
            HRMS_FRONTDESK_TASK_POLL_SECONDS,
            HRMS_FRONTDESK_EMPLOYEE_SYNC_INTERVAL_SECONDS,
        )

    def stop_worker(self) -> None:
        self._stop_event.set()
        worker = self._worker
        if worker and worker.is_alive():
            worker.join(timeout=5)

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                if self.enabled:
                    self.flush_pending()
                if self.frontdesk_enabled:
                    now = time.time()
                    if (
                        now - self._last_employee_sync_at
                        >= HRMS_FRONTDESK_EMPLOYEE_SYNC_INTERVAL_SECONDS
                    ):
                        self.sync_employees_from_hrms()
                        self._last_employee_sync_at = now
                    self.poll_face_enroll_tasks_from_hrms()
            except Exception as exc:
                logger.warning("HRMS 前台同步后台异常: %s", exc)
            self._stop_event.wait(
                max(
                    1.0,
                    min(
                        HRMS_ATTENDANCE_SYNC_WORKER_INTERVAL_SECONDS,
                        HRMS_FRONTDESK_TASK_POLL_SECONDS,
                    ),
                )
            )

    def sync_employees_from_hrms(self) -> dict[str, int]:
        if not self.frontdesk_enabled:
            return {"synced": 0, "skipped": 0, "failed": 0}
        response = self._request_json("GET", "/api/cloud/frontdesk/employees")
        employees = response.get("employees") if isinstance(response, dict) else []
        if not isinstance(employees, list):
            raise RuntimeError("HRMS employees response is not a list")
        synced = 0
        skipped = 0
        failed = 0
        for employee in employees:
            if not isinstance(employee, dict):
                skipped += 1
                continue
            try:
                result = self._register_hrms_employee(employee)
                if result["synced"]:
                    synced += 1
                else:
                    skipped += 1
            except Exception as exc:
                failed += 1
                employee_id = str(employee.get("employeeId") or "").strip()
                if employee_id:
                    try:
                        self.report_employee_sync_result(
                            employee_id,
                            status="failed",
                            message=f"员工同步失败: {exc}",
                        )
                    except Exception as report_exc:
                        logger.warning(
                            "HRMS 员工同步失败结果回传也失败: employeeId=%s error=%s",
                            employee_id,
                            report_exc,
                        )
                logger.exception(
                    "HRMS 员工同步失败: employeeId=%s name=%s error=%s",
                    employee_id,
                    employee.get("frontdeskNickname") or employee.get("name") or "",
                    exc,
                )
        logger.info(
            "HRMS 员工同步完成: total=%d synced=%d skipped=%d failed=%d",
            len(employees),
            synced,
            skipped,
            failed,
        )
        return {"synced": synced, "skipped": skipped, "failed": failed}

    def poll_face_enroll_tasks_from_hrms(self) -> int:
        if not self.frontdesk_enabled:
            return 0
        response = self._request_json("GET", "/api/cloud/frontdesk/tasks")
        tasks = response.get("tasks") if isinstance(response, dict) else []
        if not isinstance(tasks, list):
            raise RuntimeError("HRMS tasks response is not a list")
        created = 0
        for task in tasks:
            if not isinstance(task, dict):
                continue
            task_type = str(task.get("type") or "").strip()
            if task_type != "face.captureEnroll":
                logger.info("HRMS 前台任务跳过: type=%s", task_type or "unknown")
                continue
            task_id = str(task.get("taskId") or "").strip()
            if task_id and task_id in self._claimed_hrms_task_ids:
                continue
            try:
                client_task = self._create_face_capture_task(task)
                if task_id:
                    self._claimed_hrms_task_ids.add(task_id)
                created += 1
                logger.info(
                    "HRMS 人脸录入任务已转为客户端任务: hrmsTask=%s clientTask=%s target=%s",
                    task_id or "unknown",
                    client_task.id,
                    client_task.target_device_id or "*",
                )
            except Exception as exc:
                employee_id = _task_employee_id(task)
                if employee_id:
                    try:
                        self.report_face_enroll_result(
                            employee_id=employee_id,
                            status="failed",
                            message=f"创建数字人录脸任务失败: {exc}",
                            frontdesk_nickname=_task_frontdesk_name(task),
                        )
                    except Exception as report_exc:
                        logger.warning(
                            "HRMS 人脸录入任务创建失败结果回传也失败: employeeId=%s error=%s",
                            employee_id,
                            report_exc,
                        )
                logger.exception(
                    "HRMS 人脸录入任务创建失败: task=%s employeeId=%s error=%s",
                    task_id or "unknown",
                    employee_id,
                    exc,
                )
        if tasks:
            logger.info("HRMS 前台任务轮询完成: total=%d created=%d", len(tasks), created)
        return created

    def report_employee_sync_result(
        self,
        employee_id: str,
        *,
        status: str,
        message: str,
    ) -> dict[str, Any]:
        payload = {
            "employeeId": employee_id,
            "status": status,
            "message": message,
            "frontdeskDeviceId": HRMS_ATTENDANCE_DEVICE_ID,
            "registeredAt": datetime.now().isoformat(sep=" ", timespec="seconds"),
        }
        response = self._request_json(
            "POST",
            "/api/cloud/frontdesk/employee-sync-result",
            payload,
        )
        logger.info(
            "HRMS 员工同步结果已回传: employeeId=%s status=%s response=%s",
            employee_id,
            status,
            _compact_response(response),
        )
        return response

    def report_face_enroll_task_result(self, task: dict[str, Any]) -> None:
        payload = task.get("payload") if isinstance(task, dict) else {}
        if not isinstance(payload, dict):
            return
        hrms = payload.get("hrms")
        if not isinstance(hrms, dict):
            return
        employee_id = str(hrms.get("employeeId") or "").strip()
        result = task.get("result") if isinstance(task.get("result"), dict) else {}
        frontdesk_name = str(
            result.get("frontdeskNickname")
            or result.get("employeeName")
            or result.get("name")
            or hrms.get("frontdeskNickname")
            or payload.get("frontdeskNickname")
            or payload.get("name")
            or ""
        ).strip()
        if not employee_id and not frontdesk_name:
            logger.warning(
                "HRMS 人脸录入结果跳过回传: task=%s reason=missing_employee_and_name",
                task.get("id") or "",
            )
            return
        status = "success" if task.get("status") == "done" else "failed"
        message = (
            "人脸录入成功"
            if status == "success"
            else str(task.get("error") or "人脸录入失败")
        )
        self.report_face_enroll_result(
            employee_id=employee_id,
            status=status,
            message=message,
            frontdesk_nickname=frontdesk_name,
            enrolled_at=result.get("finishedAt") or "",
            tenant_id=str(hrms.get("tenantId") or payload.get("tenantId") or ""),
            device_id=str(
                result.get("deviceId")
                or result.get("frontdeskDeviceId")
                or hrms.get("deviceId")
                or HRMS_ATTENDANCE_DEVICE_ID
            ),
            client_task_id=str(task.get("id") or ""),
            task_id=str(hrms.get("taskId") or hrms.get("requestId") or ""),
        )

    def release_face_enroll_task_claim(self, task: dict[str, Any]) -> None:
        payload = task.get("payload") if isinstance(task, dict) else {}
        if not isinstance(payload, dict):
            return
        hrms = payload.get("hrms")
        if not isinstance(hrms, dict):
            return
        task_id = str(hrms.get("taskId") or "").strip()
        if task_id:
            self._claimed_hrms_task_ids.discard(task_id)
            logger.warning("HRMS 人脸录入任务回传失败，已允许后续重试: hrmsTask=%s", task_id)

    def report_face_enroll_result(
        self,
        *,
        employee_id: str,
        status: str,
        message: str,
        frontdesk_nickname: str = "",
        enrolled_at: str = "",
        tenant_id: str = "",
        device_id: str = "",
        client_task_id: str = "",
        task_id: str = "",
    ) -> dict[str, Any]:
        success = status in {"success", "ok", "done", "completed", "true"}
        payload = {
            "employeeId": employee_id,
            "tenantId": tenant_id,
            "name": frontdesk_nickname,
            "employeeName": frontdesk_nickname,
            "frontdeskNickname": frontdesk_nickname,
            "faceEnrollStatus": "success" if success else "failed",
            "message": message[:500],
            "enrolledAt": enrolled_at
            or datetime.now().isoformat(sep=" ", timespec="seconds"),
            "frontdeskDeviceId": device_id or HRMS_ATTENDANCE_DEVICE_ID,
            "clientTaskId": client_task_id,
            "taskId": task_id,
        }
        response = self._request_json(
            "POST",
            "/api/cloud/frontdesk/face/enroll-result",
            payload,
        )
        logger.info(
            "HRMS 人脸录入结果已回传: employeeId=%s status=%s response=%s",
            employee_id,
            payload["faceEnrollStatus"],
            _compact_response(response),
        )
        return response

    def _register_hrms_employee(self, employee: dict[str, Any]) -> dict[str, Any]:
        employee_id = str(employee.get("employeeId") or "").strip()
        name = _employee_frontdesk_name(employee)
        status = str(employee.get("status") or "").strip().lower()
        if status in {"离职", "已离职", "inactive", "disabled", "停用"}:
            logger.info(
                "HRMS 员工同步跳过非在职员工: employeeId=%s name=%s status=%s",
                employee_id,
                name,
                employee.get("status") or "",
            )
            return {"synced": False, "reason": "inactive"}
        if not name:
            raise RuntimeError("HRMS employee has no usable frontdesk name")

        from config import EMPLOYEES_DIR
        from core.attendance_db import AttendanceDB
        from core.employee_names import normalize_employee_name, tenant_employee_directory

        normalized_name = normalize_employee_name(name)
        db = AttendanceDB()
        inserted = db.register_employee(normalized_name, DEFAULT_TENANT_ID)
        tenant_employee_directory(
            EMPLOYEES_DIR,
            DEFAULT_TENANT_ID,
            normalized_name,
        ).mkdir(parents=True, exist_ok=True)
        frontdesk = employee.get("frontdesk") if isinstance(employee.get("frontdesk"), dict) else {}
        if employee_id and not frontdesk.get("registered"):
            message = (
                "员工已写入智慧前台"
                if inserted
                else "员工已存在于智慧前台"
            )
            try:
                self.report_employee_sync_result(
                    employee_id,
                    status="success",
                    message=message,
                )
            except Exception as exc:
                logger.warning(
                    "HRMS 员工同步成功但结果回传失败，等待下次同步重试: employeeId=%s name=%s error=%s",
                    employee_id,
                    normalized_name,
                    exc,
                )
        logger.info(
            "HRMS 员工已同步到数字人: employeeId=%s name=%s inserted=%s",
            employee_id,
            normalized_name,
            inserted,
        )
        return {"synced": True, "inserted": inserted, "name": normalized_name}

    def _create_face_capture_task(self, task: dict[str, Any]):
        employee = task.get("employee") if isinstance(task.get("employee"), dict) else {}
        payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}
        if employee:
            self._register_hrms_employee(employee)
        name = str(payload.get("name") or _employee_frontdesk_name(employee)).strip()
        if not name:
            raise RuntimeError("HRMS face capture task missing employee name")
        employee_id = str(payload.get("employeeId") or employee.get("employeeId") or "").strip()
        if not employee_id:
            raise RuntimeError("HRMS face capture task missing employeeId")
        from core.client_tasks import get_client_task_queue

        client_payload = {
            "name": name,
            "frontdeskNickname": str(
                payload.get("frontdeskNickname")
                or employee.get("frontdeskNickname")
                or name
            ),
            "cameraIndex": payload.get("cameraIndex"),
            "warmupFrames": payload.get("warmupFrames"),
            "hrms": {
                "employeeId": employee_id,
                "taskId": str(task.get("taskId") or ""),
                "frontdeskNickname": str(
                    payload.get("frontdeskNickname")
                    or employee.get("frontdeskNickname")
                    or name
                ),
            },
        }
        return get_client_task_queue().create(
            "capture_face_enroll",
            client_payload,
            target_device_id=HRMS_FRONTDESK_TASK_TARGET_DEVICE_ID,
            tenant_id=DEFAULT_TENANT_ID,
        )


    def _payload_from_record(
        self, record: dict[str, Any], *, action: str, status: str
    ) -> dict[str, Any]:
        punched_time = (
            record.get("check_in") if action == "check-in" else record.get("check_out")
        )
        punched_at = _combine_date_time(
            str(record.get("date") or ""), str(punched_time or "")
        )
        tenant_id = normalize_tenant_id(str(record.get("tenant_id") or DEFAULT_TENANT_ID))
        name = str(record.get("name") or "").strip()
        return {
            "externalId": f"cv-{tenant_id}-{record.get('id')}-{action}",
            "tenantId": tenant_id,
            "name": name,
            "frontdeskNickname": name,
            "deviceId": HRMS_ATTENDANCE_DEVICE_ID,
            "action": action,
            "punchedAt": punched_at,
            "date": str(record.get("date") or punched_at[:10]),
            "status": status,
            "durationMinutes": record.get("duration"),
            "source": "cv-frontdesk",
        }

    def _with_employee_id(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("employeeId"):
            return payload
        name = str(payload.get("frontdeskNickname") or payload.get("name") or "").strip()
        employee_id = self._employee_id_for_name(name)
        if employee_id:
            payload["employeeId"] = employee_id
        else:
            logger.warning("HRMS 员工映射未命中: name=%s action=%s", name, payload.get("action"))
        return payload

    def _employee_id_for_name(self, name: str) -> str:
        if not name:
            return ""
        mapping = self._employee_mapping()
        return mapping.get(name.strip()) or ""

    def _employee_mapping(self) -> dict[str, str]:
        now = time.time()
        with self._lock:
            if (
                self._employee_cache
                and now - self._employee_cache_at < HRMS_ATTENDANCE_EMPLOYEE_CACHE_SECONDS
            ):
                return dict(self._employee_cache)
        response = self._request_json("GET", "/api/cloud/frontdesk/employees")
        employees = response.get("employees") if isinstance(response, dict) else []
        mapping: dict[str, str] = {}
        if isinstance(employees, list):
            for item in employees:
                if not isinstance(item, dict):
                    continue
                employee_id = str(item.get("employeeId") or "").strip()
                if not employee_id:
                    continue
                for key in (
                    item.get("frontdeskNickname"),
                    item.get("name"),
                    item.get("employeeNo"),
                ):
                    text = str(key or "").strip()
                    if text:
                        mapping[text] = employee_id
        with self._lock:
            self._employee_cache = mapping
            self._employee_cache_at = now
        logger.info("HRMS 员工映射已刷新: count=%d", len(mapping))
        return dict(mapping)

    def _request_json(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        body = b""
        headers = {"Accept": "application/json"}
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            )
            headers["Content-Type"] = "application/json"
        timestamp = str(int(time.time()))
        signature_payload = f"{method.upper()}\n{path}\n{timestamp}\n".encode("utf-8") + body
        headers.update({
            "x-api-key": HRMS_ATTENDANCE_API_KEY,
            "x-timestamp": timestamp,
            "x-signature": hmac.new(
                HRMS_ATTENDANCE_API_SECRET.encode("utf-8"),
                signature_payload,
                hashlib.sha256,
            ).hexdigest(),
        })
        request = urllib.request.Request(
            HRMS_ATTENDANCE_BASE_URL + path,
            data=body if payload is not None else None,
            headers=headers,
            method=method.upper(),
        )
        try:
            with urllib.request.urlopen(
                request, timeout=HRMS_ATTENDANCE_SYNC_TIMEOUT_SECONDS
            ) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:500]
            raise RuntimeError(f"HRMS HTTP {exc.code}: {detail}") from exc
        return json.loads(raw.decode("utf-8") or "{}")


def _combine_date_time(date_text: str, time_text: str) -> str:
    if date_text and time_text:
        return f"{date_text} {time_text}"
    return datetime.now().isoformat(sep=" ", timespec="seconds")


def _compact_response(response: dict[str, Any]) -> str:
    return json.dumps(
        {
            "ok": response.get("ok"),
            "inserted": response.get("inserted"),
            "updated": response.get("updated"),
            "total": response.get("total"),
            "employee": bool(response.get("employee")),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _employee_frontdesk_name(employee: dict[str, Any]) -> str:
    return str(
        employee.get("frontdeskNickname")
        or employee.get("name")
        or employee.get("employeeNo")
        or ""
    ).strip()


def _task_employee_id(task: dict[str, Any]) -> str:
    payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}
    employee = task.get("employee") if isinstance(task.get("employee"), dict) else {}
    return str(payload.get("employeeId") or employee.get("employeeId") or "").strip()


def _task_frontdesk_name(task: dict[str, Any]) -> str:
    payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}
    employee = task.get("employee") if isinstance(task.get("employee"), dict) else {}
    return str(
        payload.get("frontdeskNickname")
        or payload.get("name")
        or _employee_frontdesk_name(employee)
    ).strip()


_syncer = HrmsAttendanceSyncer()


def get_hrms_attendance_syncer() -> HrmsAttendanceSyncer:
    return _syncer

"""Business services backing the FastAPI company integration layer."""

from __future__ import annotations

import shutil
import time
import uuid
import logging
from pathlib import Path
from typing import BinaryIO

import cv2
import numpy as np

from config import (
    API_CAPTURE_CAMERA_INDEX,
    API_CAPTURE_WARMUP_FRAMES,
    API_UPLOAD_DIR,
    EMPLOYEES_DIR,
)
from core.attendance_db import AttendanceDB
from core.employee_names import normalize_employee_name, tenant_employee_directory
from core.events import EventBus
from core.hrms_attendance_sync import get_hrms_attendance_syncer
from core.local_enroll import IMAGE_EXTENSIONS, enroll_from_payload
from core.redis_checkin import RedisCheckIn
from core.vector_db import EMBEDDING_DIM, VectorDB
from core.tenant import DEFAULT_TENANT_ID, normalize_tenant_id

logger = logging.getLogger("uvicorn.error")


class ApiError(RuntimeError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def normalize_name(name: str) -> str:
    try:
        return normalize_employee_name(name)
    except ValueError as exc:
        raise ApiError(str(exc), 400) from exc


class EmployeeService:
    def __init__(self, tenant_id: str = DEFAULT_TENANT_ID):
        self.tenant_id = normalize_tenant_id(tenant_id)
        self.attendance_db = AttendanceDB()

    def list_employees(self) -> dict:
        mysql_names = set(self.attendance_db.list_employees(self.tenant_id))
        vector_names: set[str] = set()
        try:
            vector_names = set(VectorDB().list_employees(self.tenant_id))
        except Exception:
            vector_names = set()
        names = sorted(mysql_names | vector_names)
        return {"tenantId": self.tenant_id, "names": names, "count": len(names)}

    def create_employee(self, name: str) -> dict:
        name = normalize_name(name)
        inserted = self.attendance_db.register_employee(name, self.tenant_id)
        tenant_employee_directory(EMPLOYEES_DIR, self.tenant_id, name).mkdir(
            parents=True, exist_ok=True
        )
        return {"tenantId": self.tenant_id, "name": name, "inserted": inserted}

    def enroll_employee(self, name: str, photo_paths: list[str], folder: str | None = None) -> dict:
        name = normalize_name(name)
        payload = {
            "tenantId": self.tenant_id,
            "name": name,
            "photoPaths": photo_paths,
            "folder": folder,
        }
        try:
            return enroll_from_payload(payload)
        except (ValueError, FileNotFoundError) as exc:
            raise ApiError(str(exc), 400) from exc

    def enroll_employee_embeddings(self, name: str, embeddings: list[dict]) -> dict:
        name = normalize_name(name)
        if not embeddings:
            raise ApiError("embeddings are required", 400)

        rows = []
        skipped = []
        for index, item in enumerate(embeddings, start=1):
            raw_embedding = item.get("embedding")
            if not isinstance(raw_embedding, list) or len(raw_embedding) != EMBEDDING_DIM:
                skipped.append({"index": index, "reason": "invalid embedding dimension"})
                continue
            arr = np.array(raw_embedding, dtype=np.float32)
            norm = float(np.linalg.norm(arr))
            if not np.isfinite(norm) or norm <= 0:
                skipped.append({"index": index, "reason": "invalid embedding norm"})
                continue
            arr = arr / norm
            angle = str(item.get("angle") or "client")[:32]
            photo_path = str(item.get("photo_path") or item.get("photoPath") or "")
            rows.append((arr, angle, photo_path))

        if not rows:
            raise ApiError("no usable face embeddings provided", 400)

        vector_db = VectorDB()
        vector_db.upsert_employee(name, rows, self.tenant_id)

        attendance_db = AttendanceDB()
        inserted = attendance_db.register_employee(name, self.tenant_id)
        logger.info(
            "员工向量录入完成: tenant=%s name=%s embeddings=%d skipped=%d inserted=%s",
            self.tenant_id,
            name,
            len(rows),
            len(skipped),
            inserted,
        )
        return {
            "ok": True,
            "tenantId": self.tenant_id,
            "name": name,
            "inserted": inserted,
            "embeddings": len(rows),
            "skipped": skipped,
            "source": "client_embeddings",
        }

    def delete_employee(self, name: str) -> dict:
        name = normalize_name(name)
        deleted_from_mysql = self.attendance_db.delete_employee(name, self.tenant_id)
        deleted_from_vector = False
        try:
            vector_db = VectorDB()
            deleted_from_vector = name in set(vector_db.list_employees(self.tenant_id))
            vector_db.delete_employee(name, self.tenant_id)
        except Exception as exc:
            raise ApiError(f"delete face embeddings failed: {exc}", 500) from exc
        return {
            "tenantId": self.tenant_id,
            "name": name,
            "deleted": deleted_from_mysql or deleted_from_vector,
            "deletedFromEmployeeTable": deleted_from_mysql,
            "deletedFromFaceDb": deleted_from_vector,
        }


class AttendanceService:
    def __init__(self, tenant_id: str = DEFAULT_TENANT_ID):
        self.tenant_id = normalize_tenant_id(tenant_id)
        self.attendance_db = AttendanceDB()
        self._checkin_store: RedisCheckIn | None = None
        self._event_bus: EventBus | None = None

    @property
    def checkin_store(self) -> RedisCheckIn:
        """Delay Redis initialization until a mutating attendance operation needs it."""
        if self._checkin_store is None:
            self._checkin_store = RedisCheckIn(self.tenant_id)
        return self._checkin_store

    @property
    def event_bus(self) -> EventBus:
        """Avoid opening an event-bus connection for read-only attendance queries."""
        if self._event_bus is None:
            self._event_bus = EventBus(tenant_id=self.tenant_id)
        return self._event_bus

    def check_in(self, name: str, force: bool = False) -> dict:
        name = normalize_name(name)
        if not self.attendance_db.employee_exists(name, self.tenant_id):
            raise ApiError("employee not found", 404)
        if not force and self.checkin_store.is_checked_in_today(name, self.tenant_id):
            return {
                "name": name,
                "checkedIn": False,
                "reason": "already checked in today",
                "records": self.attendance_db.get_today_records(name, self.tenant_id),
            }
        row_id = self.attendance_db.check_in(name, self.tenant_id)
        self.checkin_store.mark_checked_in(name, self.tenant_id)
        self.event_bus.checkin(name, row_id, 1.0, tenant_id=self.tenant_id)
        get_hrms_attendance_syncer().enqueue_check_in(
            self.attendance_db,
            tenant_id=self.tenant_id,
            name=name,
            row_id=row_id,
        )
        return {
            "tenantId": self.tenant_id,
            "name": name,
            "checkedIn": True,
            "rowId": row_id,
        }

    def check_out(self, name: str, force: bool = False) -> dict:
        name = normalize_name(name)
        if not self.attendance_db.employee_exists(name, self.tenant_id):
            raise ApiError("employee not found", 404)
        if not force and self.checkin_store.is_checked_out_today(name, self.tenant_id):
            return {
                "name": name,
                "checkedOut": False,
                "reason": "already checked out today",
                "records": self.attendance_db.get_today_records(name, self.tenant_id),
            }
        duration = self.attendance_db.check_out(name, self.tenant_id)
        if duration is None:
            raise ApiError("no open check-in record for today", 409)
        self.checkin_store.reset_checkin(name, self.tenant_id)
        self.event_bus.checkout(name, 0, duration, tenant_id=self.tenant_id)
        get_hrms_attendance_syncer().enqueue_check_out(
            self.attendance_db,
            tenant_id=self.tenant_id,
            name=name,
        )
        return {
            "tenantId": self.tenant_id,
            "name": name,
            "checkedOut": True,
            "durationMinutes": duration,
        }

    def today_records(self, name: str) -> dict:
        name = normalize_name(name)
        return {
            "tenantId": self.tenant_id,
            "name": name,
            "records": self.attendance_db.get_today_records(name, self.tenant_id),
        }


class PhotoCaptureService:
    def __init__(self, employee_service: EmployeeService):
        self.employee_service = employee_service

    def save_upload(self, name: str, filename: str, file: BinaryIO) -> str:
        name = normalize_name(name)
        suffix = Path(filename or "").suffix.lower()
        if suffix not in IMAGE_EXTENSIONS:
            raise ApiError("unsupported image type", 400)
        employee_upload_root = tenant_employee_directory(
            Path(API_UPLOAD_DIR) / "uploads",
            self.employee_service.tenant_id,
            name,
        )
        target_dir = employee_upload_root / uuid.uuid4().hex
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"upload{suffix}"
        with open(target, "wb") as f:
            total = 0
            while True:
                chunk = file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                f.write(chunk)
        logger.info("员工录入上传文件已保存: name=%s file=%s bytes=%d", name, target.name, total)
        return str(target)

    def enroll_from_uploaded_files(self, name: str, files: list[tuple[str, BinaryIO]]) -> dict:
        logger.info("员工录入准备保存上传文件: name=%s files=%d", name, len(files))
        paths = [self.save_upload(name, filename, file) for filename, file in files]
        try:
            logger.info("员工录入开始提取向量: name=%s files=%d", name, len(paths))
            return self.employee_service.enroll_employee(name, paths)
        finally:
            for path in paths:
                upload_run_dir = Path(path).parent
                if upload_run_dir.is_dir():
                    shutil.rmtree(upload_run_dir, ignore_errors=True)

    def capture_and_enroll(
        self,
        name: str,
        camera_index: int | None = None,
        warmup_frames: int | None = None,
    ) -> dict:
        name = normalize_name(name)
        camera_index = API_CAPTURE_CAMERA_INDEX if camera_index is None else camera_index
        warmup_frames = (
            API_CAPTURE_WARMUP_FRAMES if warmup_frames is None else max(0, warmup_frames)
        )
        target_dir = tenant_employee_directory(
            Path(API_UPLOAD_DIR) / "captures",
            self.employee_service.tenant_id,
            name,
        )
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"capture_{time.strftime('%Y%m%d_%H%M%S')}.jpg"

        cap = cv2.VideoCapture(camera_index)
        if not cap.isOpened():
            raise ApiError("camera open failed", 503)
        try:
            frame = None
            for _ in range(warmup_frames + 1):
                ok, current = cap.read()
                if ok:
                    frame = current
            if frame is None:
                raise ApiError("camera frame capture failed", 503)
            if not cv2.imwrite(str(target), frame):
                raise ApiError("capture image save failed", 500)
        finally:
            cap.release()

        result = self.employee_service.enroll_employee(name, [str(target)])
        result["capturePath"] = str(target)
        if target_dir.is_dir():
            shutil.rmtree(target_dir, ignore_errors=True)
        return result

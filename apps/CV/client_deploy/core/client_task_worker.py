"""Polls server-side tasks that must run on this frontdesk client."""

from __future__ import annotations

import logging
import os
import threading
import time
import traceback
from urllib.parse import quote

from config.common import DEVICE_ID, get_bool, get_float

logger = logging.getLogger(__name__)

TASK_ACTION_CAPTURE_FACE = "capture_face_enroll"
TASK_ACTION_ADJUST_SYSTEM_VOLUME = "adjust_system_volume"
SUPPORTED_TASK_ACTIONS = (
    TASK_ACTION_CAPTURE_FACE,
    TASK_ACTION_ADJUST_SYSTEM_VOLUME,
)
CLIENT_TASKS_ENABLED = get_bool("CLIENT_TASKS_ENABLED", True)
CLIENT_TASK_POLL_SECONDS = get_float("CLIENT_TASK_POLL_SECONDS", 2.0)


class ClientTaskWorker(threading.Thread):
    def __init__(
        self,
        client=None,
        *,
        device_id: str = DEVICE_ID,
        poll_seconds: float = CLIENT_TASK_POLL_SECONDS,
    ) -> None:
        super().__init__(name="ClientTaskWorker", daemon=True)
        if client is None:
            from core.api_client import SignedApiClient

            client = SignedApiClient(timeout=8.0)
        self.client = client
        self.device_id = device_id
        self.poll_seconds = max(0.5, poll_seconds)
        self._stop_event = threading.Event()
        self._busy = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()
        self.join(timeout=5)

    def run(self) -> None:
        if not CLIENT_TASKS_ENABLED:
            logger.info("客户端任务轮询已关闭: CLIENT_TASKS_ENABLED=0")
            return
        logger.info("客户端任务轮询已启动: device=%s interval=%.1fs", self.device_id, self.poll_seconds)
        while not self._stop_event.is_set():
            try:
                if not self._busy.is_set():
                    self._poll_once()
            except Exception as exc:
                logger.warning("客户端任务轮询异常: %s", exc)
            self._stop_event.wait(self.poll_seconds)

    def _poll_once(self) -> None:
        supported_actions = ",".join(quote(action) for action in SUPPORTED_TASK_ACTIONS)
        data = self.client.get(
            (
                f"/api/v1/client-tasks/next?device_id={quote(self.device_id)}"
                f"&supported_actions={supported_actions}"
            ),
            timeout=8.0,
        )
        task = data.get("data")
        if not task:
            return
        self._busy.set()
        threading.Thread(
            target=self._run_task,
            args=(task,),
            name=f"ClientTask:{task.get('action')}",
            daemon=True,
        ).start()

    def _run_task(self, task: dict) -> None:
        task_id = str(task.get("id") or "")
        action = str(task.get("action") or "")
        logger.info("开始执行客户端任务: id=%s action=%s payload=%s", task_id, action, task.get("payload"))
        ok = False
        result: dict = {}
        error = ""
        try:
            if action == TASK_ACTION_CAPTURE_FACE:
                result = self._run_face_capture(task.get("payload") or {})
                ok = True
            elif action == TASK_ACTION_ADJUST_SYSTEM_VOLUME:
                result = self._run_system_volume(task.get("payload") or {})
                ok = True
            else:
                error = f"unsupported task action: {action}"
        except BaseException as exc:
            error = f"{type(exc).__name__}: {exc}"
            logger.error("客户端任务执行失败: id=%s\n%s", task_id, traceback.format_exc())
        finally:
            try:
                self.client.post(
                    f"/api/v1/client-tasks/{task_id}/complete",
                    {"ok": ok, "result": result, "error": error},
                    timeout=15.0,
                )
            except Exception as exc:
                logger.warning("客户端任务结果上报失败: id=%s error=%s", task_id, exc)
            self._busy.clear()

    def _run_face_capture(self, payload: dict) -> dict:
        name_source = "task-payload"
        name = str(payload.get("name") or "").strip()
        if not name:
            name_source = "device-input"
            name = self._prompt_face_capture_name(payload)

        os.environ.setdefault("FACE_CAPTURE_ENROLL_VIA_API", "1")
        camera_index = payload.get("cameraIndex")
        from tools.capture_faces import main as capture_faces_main

        started_at = time.time()
        logger.info(
            "客户端人脸录入准备开始: device=%s camera=%s nameSource=%s",
            self.device_id,
            camera_index,
            name_source,
        )
        capture_faces_main(name, camera_index=_optional_int(camera_index))
        return {
            "name": name,
            "frontdeskNickname": name,
            "employeeName": name,
            "nameSource": name_source,
            "deviceId": self.device_id,
            "cameraIndex": camera_index,
            "finishedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
            "durationSeconds": round(time.time() - started_at, 2),
        }

    def _prompt_face_capture_name(self, payload: dict) -> str:
        prompt = str(payload.get("namePrompt") or "请输入本次录入人脸的员工姓名").strip()
        name = ""
        try:
            import tkinter as tk
            from tkinter import simpledialog

            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            name = simpledialog.askstring("人脸录入", prompt, parent=root) or ""
            root.destroy()
        except BaseException as exc:
            logger.warning("设备端姓名弹窗不可用，尝试命令行输入: error=%s", exc)
            try:
                name = input(f"{prompt}: ").strip()
            except BaseException as input_exc:
                raise RuntimeError("设备端未能输入员工姓名，无法执行人脸录入任务") from input_exc
        name = name.strip()
        if not name:
            raise RuntimeError("设备端未输入员工姓名，已取消人脸录入任务")
        return name

    def _run_system_volume(self, payload: dict) -> dict:
        from core.system_volume import adjust_system_volume

        started_at = time.time()
        result = adjust_system_volume(payload)
        result["durationSeconds"] = round(time.time() - started_at, 2)
        return result


def _optional_int(value) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


"""Shared camera frame hub and camera owner thread."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable

import cv2

from config import CAMERA_BUFFER_SIZE, CAMERA_INDEX, FRAME_HEIGHT, FRAME_WIDTH
from core.camera_control import get_camera_pause_request, mark_camera_status

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FrameSnapshot:
    sequence: int
    captured_at: float
    frame: object


class FrameHub:
    """Latest-frame fanout for independent consumers.

    The hub intentionally keeps only the newest frame. Slow consumers skip old
    frames instead of blocking camera capture or each other.
    """

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._latest: FrameSnapshot | None = None
        self._closed = False
        self._published = 0

    @property
    def published(self) -> int:
        return self._published

    def publish(self, frame) -> None:
        with self._condition:
            self._published += 1
            self._latest = FrameSnapshot(
                sequence=self._published,
                captured_at=time.time(),
                frame=frame,
            )
            self._condition.notify_all()

    def wait_next(
        self,
        last_sequence: int = 0,
        timeout: float = 0.5,
        copy_frame: bool = True,
    ) -> FrameSnapshot | None:
        deadline = time.time() + timeout
        with self._condition:
            while not self._closed:
                if self._latest is not None and self._latest.sequence > last_sequence:
                    snapshot = self._latest
                    frame = snapshot.frame.copy() if copy_frame else snapshot.frame
                    return FrameSnapshot(snapshot.sequence, snapshot.captured_at, frame)
                remaining = deadline - time.time()
                if remaining <= 0:
                    return None
                self._condition.wait(timeout=remaining)
            return None

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()


class CameraManager:
    """Owns camera reads and publishes flipped frames to FrameHub."""

    def __init__(
        self,
        cap,
        hub: FrameHub,
        *,
        owner: str = "app.py",
        detail: str = "CameraManager",
    ) -> None:
        self._cap = cap
        self._hub = hub
        self._owner = owner
        self._detail = detail
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._frames = 0
        self._started_at = 0.0
        self._last_fps_log_at = 0.0
        self._last_error = ""

    @property
    def frames(self) -> int:
        return self._frames

    @property
    def last_error(self) -> str:
        return self._last_error

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._started_at = time.time()
        self._last_fps_log_at = self._started_at
        self._thread = threading.Thread(
            target=self._run,
            name="CameraManager",
            daemon=True,
        )
        self._thread.start()
        logger.info("CameraManager 已启动: index=%s", CAMERA_INDEX)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        self._release_camera()
        self._hub.close()
        elapsed = max(0.001, time.time() - self._started_at)
        logger.info(
            "CameraManager 已停止 (frames=%d, avg_fps=%.2f)",
            self._frames,
            self._frames / elapsed,
        )

    def is_alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _run(self) -> None:
        mark_camera_status("active", owner=self._owner, detail=self._detail)
        while not self._stop_event.is_set():
            if self._handle_pause_request():
                continue

            if self._cap is None or not self._cap.isOpened():
                if not self._open_camera():
                    time.sleep(0.25)
                    continue

            ret, frame = self._cap.read()
            if not ret:
                self._last_error = "camera read failed"
                logger.warning("CameraManager 读取摄像头失败，尝试重连")
                self._release_camera()
                time.sleep(0.2)
                continue

            frame = cv2.flip(frame, 1)
            self._hub.publish(frame)
            self._frames += 1
            self._log_fps_if_needed()

    def _handle_pause_request(self) -> bool:
        pause_request = get_camera_pause_request()
        if not pause_request:
            return False

        owner = str(pause_request.get("owner") or "unknown")
        logger.info("摄像头暂停请求: %s，CameraManager 释放摄像头", owner)
        self._release_camera()
        mark_camera_status("released", owner=owner, detail=self._detail)

        while get_camera_pause_request() and not self._stop_event.is_set():
            time.sleep(0.25)

        if self._stop_event.is_set():
            return True

        logger.info("摄像头暂停结束，CameraManager 恢复摄像头")
        if self._open_camera():
            mark_camera_status("active", owner=self._owner, detail="camera resumed")
        else:
            mark_camera_status("resume_failed", owner=owner, detail="camera open failed")
        return True

    def _open_camera(self) -> bool:
        self._cap = cv2.VideoCapture(CAMERA_INDEX)
        if not self._cap.isOpened():
            self._last_error = "camera open failed"
            return False
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
        self._cap.set(cv2.CAP_PROP_BUFFERSIZE, CAMERA_BUFFER_SIZE)
        self._last_error = ""
        return True

    def _release_camera(self) -> None:
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None

    def _log_fps_if_needed(self) -> None:
        now = time.time()
        if now - self._last_fps_log_at < 10.0:
            return
        elapsed = max(0.001, now - self._started_at)
        logger.debug(
            "CameraManager FPS: %.2f published=%d",
            self._frames / elapsed,
            self._hub.published,
        )
        self._last_fps_log_at = now


class FrameConsumer:
    """Pulls latest frames from FrameHub and forwards them to one consumer."""

    def __init__(
        self,
        hub: FrameHub,
        handler: Callable,
        *,
        name: str,
        copy_frame: bool = True,
    ) -> None:
        self._hub = hub
        self._handler = handler
        self._name = name
        self._copy_frame = copy_frame
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_sequence = 0
        self._received = 0
        self._errors = 0

    @property
    def received(self) -> int:
        return self._received

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run,
            name=self._name,
            daemon=True,
        )
        self._thread.start()
        logger.info("FrameConsumer 已启动: %s", self._name)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        logger.info(
            "FrameConsumer 已停止: %s (received=%d, errors=%d)",
            self._name,
            self._received,
            self._errors,
        )

    def _run(self) -> None:
        while not self._stop_event.is_set():
            snapshot = self._hub.wait_next(
                self._last_sequence,
                timeout=0.2,
                copy_frame=self._copy_frame,
            )
            if snapshot is None:
                continue
            self._last_sequence = snapshot.sequence
            try:
                self._handler(snapshot.frame)
                self._received += 1
            except Exception:
                self._errors += 1
                logger.exception("FrameConsumer 处理异常: %s", self._name)

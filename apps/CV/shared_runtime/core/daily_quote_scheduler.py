"""In-process scheduler for daily avatar quote generation."""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from config import CACHE_DIR, DAILY_TTS_TEXTS_FILE
from core.tts_texts import reload_daily_texts
from tools.generate_daily_tts_texts import generate_daily_texts

logger = logging.getLogger(__name__)
RELOAD_REQUEST_FILE = Path(CACHE_DIR) / "daily_tts_reload.json"


class DailyQuoteScheduler(threading.Thread):
    def __init__(self, hour: int = 6, minute: int = 0):
        super().__init__(name="DailyQuoteScheduler", daemon=True)
        self.hour = hour
        self.minute = minute
        self._stop_event = threading.Event()
        self._last_reload_request_at = 0.0

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        self._ensure_today_generated()
        while not self._stop_event.is_set():
            next_run = self._next_run_time()
            while not self._stop_event.is_set():
                self._reload_if_requested()
                wait_seconds = (next_run - datetime.now()).total_seconds()
                if wait_seconds <= 0:
                    break
                if self._stop_event.wait(min(2.0, wait_seconds)):
                    break
            if self._stop_event.is_set():
                break
            self._generate_for_today()

    def _reload_if_requested(self) -> None:
        try:
            payload = json.loads(RELOAD_REQUEST_FILE.read_text(encoding="utf-8"))
            requested_at = float(payload.get("requestedAt") or 0.0)
        except Exception:
            return
        if requested_at <= self._last_reload_request_at:
            return
        self._last_reload_request_at = requested_at
        try:
            reload_daily_texts()
            logger.info("每日数字人语录已按控制台请求重新加载")
        except Exception as exc:
            logger.warning("每日数字人语录重新加载失败: %s", exc)

    def _ensure_today_generated(self) -> None:
        if self._has_today_texts():
            reload_daily_texts()
            return
        self._generate_for_today()

    def _generate_for_today(self) -> None:
        try:
            output_path = generate_daily_texts(allow_fallback=True)
            reload_daily_texts()
            logger.info("每日数字人语录已刷新: %s", output_path)
        except Exception as exc:
            logger.warning("每日数字人语录刷新失败，继续使用现有语录: %s", exc)

    def _has_today_texts(self) -> bool:
        path = Path(DAILY_TTS_TEXTS_FILE)
        if not path.exists():
            return False
        try:
            with path.open("r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception:
            return False
        return payload.get("date") == date.today().isoformat()

    def _next_run_time(self) -> datetime:
        now = datetime.now()
        next_run = now.replace(
            hour=self.hour,
            minute=self.minute,
            second=0,
            microsecond=0,
        )
        if next_run <= now:
            next_run += timedelta(days=1)
        return next_run

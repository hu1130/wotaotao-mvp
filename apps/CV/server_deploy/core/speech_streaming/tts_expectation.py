"""Async lifecycle for one expected Omni TTS response."""

from __future__ import annotations

import asyncio
import time


class TtsExpectationError(RuntimeError):
    pass


class ExternalRagTimeout(TimeoutError):
    """External RAG exceeded a specific response stage deadline."""

    def __init__(self, stage: str, timeout_seconds: float):
        self.stage = stage
        self.timeout_seconds = float(timeout_seconds)
        super().__init__(
            f"external RAG {stage} timeout after {self.timeout_seconds:.1f}s"
        )


class TtsExpectation:
    """Tracks first audible output and full completion as separate signals."""

    def __init__(self) -> None:
        self.expected_type = ""
        self.expected_text = ""
        self.received_bytes = 0
        self.started_at = 0.0
        self._first_audio: asyncio.Future[float] | None = None
        self._completed: asyncio.Future[float] | None = None

    @property
    def active(self) -> bool:
        return self._completed is not None

    def begin(self, expected_type: str, *, expected_text: str = "") -> None:
        if self.active:
            raise TtsExpectationError(
                f"already waiting for TTS type {self.expected_type}"
            )
        loop = asyncio.get_running_loop()
        self.expected_type = expected_type
        self.expected_text = expected_text
        self.received_bytes = 0
        self.started_at = time.perf_counter()
        self._first_audio = loop.create_future()
        self._completed = loop.create_future()

    def record_audio(self, tts_type: str, size: int) -> None:
        if tts_type == self.expected_type:
            self.received_bytes += max(0, int(size))

    def mark_first_audio(self, tts_type: str) -> float | None:
        future = self._first_audio
        if tts_type != self.expected_type or future is None or future.done():
            return None
        elapsed_ms = max(0.0, (time.perf_counter() - self.started_at) * 1000)
        future.set_result(elapsed_ms)
        return elapsed_ms

    def mark_completed(self, ended_types: set[str], *, bytes_per_second: int) -> bool:
        future = self._completed
        if (
            not self.expected_type
            or self.expected_type not in ended_types
            or future is None
            or future.done()
        ):
            return False
        future.set_result(self.received_bytes / max(1, int(bytes_per_second)))
        return True

    async def wait_for_completion(self, timeout_seconds: float) -> float:
        completed = self._require_completed()
        return await asyncio.wait_for(
            asyncio.shield(completed),
            timeout=max(0.05, float(timeout_seconds)),
        )

    async def wait_for_external(
        self,
        *,
        first_audio_timeout_seconds: float,
        completion_timeout_seconds: float,
    ) -> float:
        first_audio = self._require_first_audio()
        completed = self._require_completed()
        first_timeout = max(0.05, float(first_audio_timeout_seconds))
        completion_timeout = max(0.05, float(completion_timeout_seconds))

        done, _ = await asyncio.wait(
            {first_audio, completed},
            timeout=first_timeout,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if not done:
            if first_audio.done():
                done = {first_audio}
            elif completed.done():
                done = {completed}
            else:
                raise ExternalRagTimeout("first_audio", first_timeout)
        if completed in done and first_audio not in done:
            return completed.result()
        first_audio.result()
        try:
            return await self.wait_for_completion(completion_timeout)
        except TimeoutError as exc:
            if completed.done():
                return completed.result()
            raise ExternalRagTimeout("completion", completion_timeout) from exc

    def reset(self) -> None:
        for future in (self._first_audio, self._completed):
            if future is not None and not future.done():
                future.cancel()
        self.expected_type = ""
        self.expected_text = ""
        self.received_bytes = 0
        self.started_at = 0.0
        self._first_audio = None
        self._completed = None

    def _require_first_audio(self) -> asyncio.Future[float]:
        if self._first_audio is None:
            raise TtsExpectationError("TTS expectation has not started")
        return self._first_audio

    def _require_completed(self) -> asyncio.Future[float]:
        if self._completed is None:
            raise TtsExpectationError("TTS expectation has not started")
        return self._completed

from __future__ import annotations

import asyncio
import unittest

from core.speech_streaming.tts_expectation import (
    ExternalRagTimeout,
    TtsExpectation,
)


class TtsExpectationTests(unittest.TestCase):
    def test_first_audio_timeout_identifies_stage(self) -> None:
        expectation = TtsExpectation()

        async def scenario() -> None:
            expectation.begin("external_rag")
            try:
                await expectation.wait_for_external(
                    first_audio_timeout_seconds=0.01,
                    completion_timeout_seconds=0.01,
                )
            finally:
                expectation.reset()

        with self.assertRaises(ExternalRagTimeout) as caught:
            asyncio.run(scenario())

        self.assertEqual(caught.exception.stage, "first_audio")

    def test_completion_timeout_identifies_stage_after_first_audio(self) -> None:
        expectation = TtsExpectation()

        async def scenario() -> None:
            expectation.begin("external_rag")
            expectation.record_audio("external_rag", 640)
            expectation.mark_first_audio("external_rag")
            try:
                await expectation.wait_for_external(
                    first_audio_timeout_seconds=0.01,
                    completion_timeout_seconds=0.01,
                )
            finally:
                expectation.reset()

        with self.assertRaises(ExternalRagTimeout) as caught:
            asyncio.run(scenario())

        self.assertEqual(caught.exception.stage, "completion")

    def test_completed_empty_response_returns_without_first_audio_wait(self) -> None:
        expectation = TtsExpectation()

        async def scenario() -> float:
            expectation.begin("external_rag")
            expectation.mark_completed(
                {"external_rag"},
                bytes_per_second=48000,
            )
            try:
                return await expectation.wait_for_external(
                    first_audio_timeout_seconds=0.01,
                    completion_timeout_seconds=0.01,
                )
            finally:
                expectation.reset()

        self.assertEqual(asyncio.run(scenario()), 0.0)

    def test_first_audio_and_completion_are_independent_signals(self) -> None:
        expectation = TtsExpectation()

        async def scenario() -> float:
            expectation.begin("external_rag")
            waiter = asyncio.create_task(
                expectation.wait_for_external(
                    first_audio_timeout_seconds=1.0,
                    completion_timeout_seconds=1.0,
                )
            )
            expectation.record_audio("external_rag", 48000)
            expectation.mark_first_audio("external_rag")
            await asyncio.sleep(0)
            self.assertFalse(waiter.done())
            expectation.mark_completed(
                {"external_rag"},
                bytes_per_second=48000,
            )
            try:
                return await waiter
            finally:
                expectation.reset()

        self.assertEqual(asyncio.run(scenario()), 1.0)


if __name__ == "__main__":
    unittest.main()

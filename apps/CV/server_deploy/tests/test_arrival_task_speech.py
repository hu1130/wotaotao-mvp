from __future__ import annotations

import importlib
import unittest


class ArrivalTaskSpeechTests(unittest.TestCase):
    def test_self_arrival_task_does_not_say_creator_asked(self) -> None:
        try:
            module = importlib.import_module("core.remote_recognition")
        except ModuleNotFoundError as exc:
            self.skipTest(f"remote recognition dependency unavailable: {exc}")

        text = module.RemoteRecognitionService._arrival_task_speech_text(
            {
                "creatorPersonId": "tenant:tenant-a:employee:1",
                "targetPersonId": "tenant:tenant-a:employee:1",
                "creatorName": "小游",
                "targetName": "小游",
                "content": "are you ok",
                "exactText": False,
            },
            fallback_target_name="小游",
        )

        self.assertEqual(text, "小游，are you ok")


if __name__ == "__main__":
    unittest.main()

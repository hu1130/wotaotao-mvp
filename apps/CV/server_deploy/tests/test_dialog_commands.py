from __future__ import annotations

import unittest

from core.dialog_commands import DialogCommandRouter


class DialogCommandRouterTests(unittest.TestCase):
    def test_face_capture_without_name_does_not_invent_name(self) -> None:
        router = DialogCommandRouter()

        for text in ("帮我录入人脸", "帮我录人脸", "帮我路人脸"):
            with self.subTest(text=text):
                proposal = router.route(text)

                self.assertIsNotNone(proposal)
                assert proposal is not None
                self.assertEqual(proposal.params["name"], "")

    def test_face_capture_extracts_name_from_explicit_target(self) -> None:
        router = DialogCommandRouter()

        samples = {
            "给小游录人脸": "小游",
            "给小游路人脸": "小游",
            "帮小王录入人脸": "小王",
            "录入张三的人脸": "张三",
        }
        for text, expected in samples.items():
            with self.subTest(text=text):
                proposal = router.route(text)

                self.assertIsNotNone(proposal)
                assert proposal is not None
                self.assertEqual(proposal.params["name"], expected)

    def test_face_word_without_action_is_not_face_capture(self) -> None:
        self.assertIsNone(DialogCommandRouter().route("你们的人脸识别产品怎么样"))


if __name__ == "__main__":
    unittest.main()

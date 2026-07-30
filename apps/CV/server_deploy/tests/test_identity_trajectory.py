from __future__ import annotations

import unittest

import numpy as np

from core.embedding_matcher import EmbeddingMatcher
from core.identity_trajectory import (
    FaceTrajectoryObservation,
    IdentityTrajectoryTracker,
)


def observation(
    track_id: int,
    bbox: tuple[int, int, int, int],
    *,
    name: str = "",
    similarity: float = 0.0,
    nearest_name: str = "",
) -> FaceTrajectoryObservation:
    return FaceTrajectoryObservation(
        track_id=track_id,
        bbox=bbox,
        recognized_name=name,
        similarity=similarity,
        nearest_name=nearest_name,
    )


class IdentityTrajectoryTrackerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tracker = IdentityTrajectoryTracker(
            max_gap_seconds=3.0,
            retention_seconds=10.0,
            min_nearest_similarity=0.22,
        )
        self.known_bbox = (400, 120, 720, 500)
        self.tracker.resolve(
            "frontdesk",
            [
                observation(
                    2,
                    self.known_bbox,
                    name="小游",
                    similarity=0.665,
                    nearest_name="小游",
                )
            ],
            now=100.0,
        )

    def test_new_track_inherits_identity_during_speech_deformation(self) -> None:
        recovered = self.tracker.resolve(
            "frontdesk",
            [
                observation(
                    1,
                    (410, 125, 728, 505),
                    similarity=0.325,
                    nearest_name="小游",
                )
            ],
            now=100.7,
        )

        self.assertEqual(recovered[1].name, "小游")
        self.assertEqual(recovered[1].source_track_id, 2)

    def test_immediate_strong_overlap_can_recover_blurred_face_without_embedding(self) -> None:
        recovered = self.tracker.resolve(
            "frontdesk",
            [observation(3, (402, 121, 719, 499))],
            now=100.4,
        )

        self.assertEqual(recovered[3].name, "小游")

    def test_confirmed_owner_blocks_second_face_from_inheriting_same_identity(self) -> None:
        recovered = self.tracker.resolve(
            "frontdesk",
            [
                observation(
                    2,
                    self.known_bbox,
                    name="小游",
                    similarity=0.66,
                    nearest_name="小游",
                ),
                observation(
                    8,
                    (730, 130, 1010, 490),
                    similarity=0.31,
                    nearest_name="小游",
                ),
            ],
            now=100.5,
        )

        self.assertEqual(recovered, {})

    def test_multi_face_recovery_requires_appearance_support(self) -> None:
        without_appearance = self.tracker.resolve(
            "frontdesk",
            [
                observation(4, (405, 124, 724, 503)),
                observation(5, (800, 140, 1050, 480)),
            ],
            now=100.6,
        )
        self.assertEqual(without_appearance, {})

        with_appearance = self.tracker.resolve(
            "frontdesk",
            [
                observation(
                    4,
                    (405, 124, 724, 503),
                    similarity=0.30,
                    nearest_name="小游",
                ),
                observation(5, (800, 140, 1050, 480)),
            ],
            now=100.7,
        )
        self.assertEqual(with_appearance[4].name, "小游")
        self.assertNotIn(5, with_appearance)

    def test_distant_or_expired_track_is_not_recovered(self) -> None:
        distant = self.tracker.resolve(
            "frontdesk",
            [
                observation(
                    6,
                    (900, 100, 1200, 480),
                    similarity=0.35,
                    nearest_name="小游",
                )
            ],
            now=100.5,
        )
        expired = self.tracker.resolve(
            "frontdesk",
            [
                observation(
                    7,
                    self.known_bbox,
                    similarity=0.35,
                    nearest_name="小游",
                )
            ],
            now=104.0,
        )

        self.assertEqual(distant, {})
        self.assertEqual(expired, {})

    def test_rejected_embedding_keeps_nearest_identity_as_weak_evidence(self) -> None:
        matcher = EmbeddingMatcher(
            [
                ("甲", np.asarray([1.0, 0.0, 0.0, 0.0], dtype=np.float32)),
                ("乙", np.asarray([0.0, 1.0, 0.0, 0.0], dtype=np.float32)),
                ("丙", np.asarray([0.0, 0.0, 1.0, 0.0], dtype=np.float32)),
                ("丁", np.asarray([0.0, 0.0, 0.0, 1.0], dtype=np.float32)),
            ]
        )

        candidate = matcher.match_candidate(
            np.asarray([0.51, 0.50, 0.49, 0.48], dtype=np.float32)
        )

        self.assertEqual(candidate.decision, "reject")
        self.assertIsNone(candidate.name)
        self.assertEqual(candidate.nearest_name, "甲")


if __name__ == "__main__":
    unittest.main()

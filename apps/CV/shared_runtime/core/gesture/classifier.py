"""ML-first gesture classifier with rule fallback only when model unavailable."""

from __future__ import annotations

import logging
import math
import os
from datetime import datetime

from core.gesture.schemas import (
    GestureCandidate,
    HandLandmark,
    HandObservation,
    NO_GESTURE,
    observation_to_features,
)

logger = logging.getLogger(__name__)

WRIST = 0
THUMB_CMC = 1
THUMB_MCP = 2
THUMB_IP = 3
THUMB_TIP = 4
INDEX_MCP = 5
INDEX_PIP = 6
INDEX_DIP = 7
INDEX_TIP = 8
MIDDLE_MCP = 9
MIDDLE_TIP = 12
RING_TIP = 16
PINKY_TIP = 20

FINGER_TIPS = {
    "index": 8,
    "middle": 12,
    "ring": 16,
    "pinky": 20,
}
FINGER_PIPS = {
    "index": 6,
    "middle": 10,
    "ring": 14,
    "pinky": 18,
}

MODEL_DIR = os.path.join(os.path.dirname(__file__), "model")
MODEL_PATH = os.path.join(MODEL_DIR, "gesture_classifier.joblib")


class StaticGestureClassifier:
    """ML-first gesture classifier. Rules used only when model is unavailable."""

    def __init__(self) -> None:
        self._ml_model = None
        self._ml_available = False
        self._load_ml_model()

    def _load_ml_model(self) -> None:
        if not os.path.isfile(MODEL_PATH):
            logger.warning(
                "ML gesture model not found at %s, falling back to rules only",
                MODEL_PATH,
            )
            return
        try:
            import joblib
        except ImportError:
            try:
                from sklearn.externals import joblib
            except ImportError:
                logger.warning("joblib not available, falling back to rules only")
                return
        try:
            self._ml_model = joblib.load(MODEL_PATH)
            self._ml_available = True
            classes = [str(item) for item in getattr(self._ml_model, "classes_", [])]
            modified_at = datetime.fromtimestamp(os.path.getmtime(MODEL_PATH))
            logger.info(
                "ML gesture model loaded: path=%s type=%s modified_at=%s classes=%s",
                MODEL_PATH,
                type(self._ml_model).__name__,
                modified_at.isoformat(sep=" ", timespec="seconds"),
                classes,
            )
            if NO_GESTURE not in classes:
                logger.warning(
                    "ML gesture model has no '%s' class; every detected hand will be forced into a gesture class",
                    NO_GESTURE,
                )
        except Exception as exc:
            logger.warning("Failed to load ML gesture model: %s", exc)

    def classify(self, observation: HandObservation) -> GestureCandidate:
        landmarks = observation.landmarks
        if len(landmarks) < 21:
            return self._none(observation)

        if self._ml_available:
            ml_result = self._classify_by_ml(observation)
            if ml_result is not None:
                return ml_result
            return self._candidate(observation, NO_GESTURE, 0.0, {"source": "ml"})

        states = self._finger_states(landmarks)
        rule_result = self._classify_by_rules(observation, states)
        if rule_result is not None:
            return rule_result

        return self._none(observation)

    def _classify_by_ml(self, observation: HandObservation) -> GestureCandidate | None:
        features = observation_to_features(observation)
        if features is None:
            return None
        try:
            import numpy as np

            X = np.array([features], dtype=np.float32)
            proba = self._ml_model.predict_proba(X)[0]
            idx = int(np.argmax(proba))
            confidence = float(proba[idx])
            classes = list(self._ml_model.classes_)
            label = classes[idx]
            if label == NO_GESTURE:
                return None
            return GestureCandidate(
                name=label,
                confidence=round(max(0.0, min(1.0, confidence)), 4),
                hand=observation.handedness,
                metadata={"source": "ml"},
            )
        except Exception as exc:
            logger.debug("ML classification failed: %s", exc)
            return None

    def _classify_by_rules(
        self,
        observation: HandObservation,
        states: dict[str, bool],
    ) -> GestureCandidate | None:
        thumbs_up = self._thumbs_up(observation, states)
        middle_finger = self._middle_finger(observation, states)
        peace = self._peace(observation, states)

        candidates = [thumbs_up, middle_finger, peace]
        candidates = [c for c in candidates if c.confidence > 0]
        if not candidates:
            return None

        best = max(candidates, key=lambda item: item.confidence)
        if best.confidence >= 0.7:
            return best

        return None

    def _finger_states(self, landmarks: tuple[HandLandmark, ...]) -> dict[str, bool]:
        states = {}
        for name, tip_index in FINGER_TIPS.items():
            pip_index = FINGER_PIPS[name]
            states[name] = landmarks[tip_index].y < landmarks[pip_index].y - 0.025
        return states

    def _thumbs_up(
        self,
        observation: HandObservation,
        states: dict[str, bool],
    ) -> GestureCandidate:
        landmarks = observation.landmarks
        wrist = landmarks[WRIST]
        thumb = landmarks[THUMB_TIP]
        thumb_vertical = wrist.y - thumb.y
        thumb_lateral = abs(thumb.x - wrist.x)
        palm_scale = max(0.08, self._distance(landmarks[WRIST], landmarks[MIDDLE_MCP]))
        thumb_index_gap = self._distance(landmarks[THUMB_TIP], landmarks[INDEX_TIP])
        thumb_index_cluster_gap = self._thumb_index_cluster_gap(landmarks)
        folded_count = sum(1 for name in FINGER_TIPS if not states[name])

        if thumb_index_gap <= palm_scale * 0.5:
            return self._candidate(observation, "thumbs_up", 0.0)
        if self._is_heart_like_pose(
            landmarks, states, palm_scale, thumb_index_cluster_gap
        ):
            return self._candidate(observation, "thumbs_up", 0.0)
        if folded_count < 3:
            return self._candidate(observation, "thumbs_up", 0.0)
        if thumb_vertical <= 0.12 or thumb_vertical <= thumb_lateral * 0.75:
            return self._candidate(observation, "thumbs_up", 0.0)
        confidence = min(0.98, 0.62 + folded_count * 0.08 + thumb_vertical * 0.7)
        return self._candidate(
            observation,
            "thumbs_up",
            confidence,
            {"folded_fingers": folded_count},
        )

    def _middle_finger(
        self,
        observation: HandObservation,
        states: dict[str, bool],
    ) -> GestureCandidate:
        if not states["middle"]:
            return self._candidate(observation, "middle_finger", 0.0)
        if states["index"] or states["ring"] or states["pinky"]:
            return self._candidate(observation, "middle_finger", 0.0)
        landmarks = observation.landmarks
        palm_scale = max(0.08, self._distance(landmarks[WRIST], landmarks[MIDDLE_MCP]))
        middle_length = self._distance(landmarks[MIDDLE_MCP], landmarks[MIDDLE_TIP])
        if middle_length < palm_scale * 0.6:
            return self._candidate(observation, "middle_finger", 0.0)
        confidence = min(0.93, 0.75 + middle_length * 0.5)
        return self._candidate(
            observation,
            "middle_finger",
            confidence,
            {
                "middle_length": round(middle_length, 4),
                "palm_scale": round(palm_scale, 4),
            },
        )

    def _peace(
        self,
        observation: HandObservation,
        states: dict[str, bool],
    ) -> GestureCandidate:
        if not states["index"] or not states["middle"]:
            return self._candidate(observation, "peace", 0.0)
        if states["ring"] or states["pinky"]:
            return self._candidate(observation, "peace", 0.0)
        spread = self._distance(
            observation.landmarks[INDEX_TIP],
            observation.landmarks[MIDDLE_TIP],
        )
        confidence = min(0.92, 0.68 + spread)
        return self._candidate(observation, "peace", confidence, {"spread": spread})

    def _candidate(
        self,
        observation: HandObservation,
        name: str,
        confidence: float,
        metadata: dict | None = None,
    ) -> GestureCandidate:
        return GestureCandidate(
            name=name,
            confidence=round(max(0.0, min(1.0, confidence)), 4),
            hand=observation.handedness,
            metadata=metadata or {},
        )

    def _none(self, observation: HandObservation) -> GestureCandidate:
        return self._candidate(observation, NO_GESTURE, 0.0)

    def _is_heart_like_pose(
        self,
        landmarks: tuple[HandLandmark, ...],
        states: dict[str, bool],
        palm_scale: float,
        thumb_index_cluster_gap: float,
    ) -> bool:
        folded_count = sum(
            1 for name in ("middle", "ring", "pinky") if not states[name]
        )
        return (
            folded_count >= 2
            and not states["middle"]
            and thumb_index_cluster_gap <= palm_scale * 0.45
            and self._is_index_bent(landmarks, states, palm_scale)
        )

    def _is_index_bent(
        self,
        landmarks: tuple[HandLandmark, ...],
        states: dict[str, bool],
        palm_scale: float,
    ) -> bool:
        tip = landmarks[INDEX_TIP]
        pip = landmarks[INDEX_PIP]
        dip = landmarks[INDEX_DIP]
        tip_to_pip = self._distance(tip, pip)
        tip_to_dip = self._distance(tip, dip)
        return (
            not states["index"]
            or tip.y >= pip.y - 0.06
            or tip_to_pip <= palm_scale * 0.72
            or tip_to_dip <= palm_scale * 0.45
        )

    def _thumb_index_cluster_gap(self, landmarks: tuple[HandLandmark, ...]) -> float:
        thumb_tip = landmarks[THUMB_TIP]
        return min(
            self._distance(thumb_tip, landmarks[INDEX_TIP]),
            self._distance(thumb_tip, landmarks[INDEX_DIP]),
            self._distance(thumb_tip, landmarks[INDEX_PIP]),
        )

    @staticmethod
    def _distance(a: HandLandmark, b: HandLandmark) -> float:
        return math.hypot(a.x - b.x, a.y - b.y)

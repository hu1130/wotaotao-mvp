"""MediaPipe based hand landmark detector."""

from __future__ import annotations

import logging

import cv2

from config import (
    GESTURE_DETECT_SCALE,
    GESTURE_MODEL_COMPLEXITY,
    GESTURE_MIN_DETECTION_CONFIDENCE,
    GESTURE_MIN_TRACKING_CONFIDENCE,
)
from core.gesture.schemas import HandLandmark, HandObservation

logger = logging.getLogger(__name__)


class GestureDependencyError(RuntimeError):
    """Raised when the gesture model dependency is not installed."""


class MediaPipeHandDetector:
    """Detects hands and returns normalized 21-point hand landmarks."""

    def __init__(self) -> None:
        try:
            import mediapipe as mp
        except ImportError as exc:
            raise GestureDependencyError(
                "缺少 mediapipe，无法启动手势识别。请执行: "
                "pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple"
            ) from exc

        self._mp_hands = mp.solutions.hands
        self._hands = self._mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=2,
            model_complexity=GESTURE_MODEL_COMPLEXITY,
            min_detection_confidence=GESTURE_MIN_DETECTION_CONFIDENCE,
            min_tracking_confidence=GESTURE_MIN_TRACKING_CONFIDENCE,
        )
        self._detect_scale = max(1.0, float(GESTURE_DETECT_SCALE))

    def close(self) -> None:
        self._hands.close()

    def detect(self, frame) -> list[HandObservation]:
        if self._detect_scale > 1.0:
            frame = cv2.resize(
                frame,
                None,
                fx=self._detect_scale,
                fy=self._detect_scale,
                interpolation=cv2.INTER_LINEAR,
            )
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        rgb.flags.writeable = False
        result = self._hands.process(rgb)
        if not result.multi_hand_landmarks:
            return []

        handedness_items = result.multi_handedness or []
        observations: list[HandObservation] = []
        for index, hand_landmarks in enumerate(result.multi_hand_landmarks):
            handedness = "unknown"
            confidence = 0.0
            if index < len(handedness_items):
                item = handedness_items[index].classification[0]
                handedness = str(item.label or "unknown").lower()
                confidence = float(item.score or 0.0)

            landmarks = tuple(
                HandLandmark(float(point.x), float(point.y), float(point.z))
                for point in hand_landmarks.landmark
            )
            observations.append(
                HandObservation(
                    landmarks=landmarks,
                    handedness=handedness,
                    confidence=confidence,
                )
            )
        return observations

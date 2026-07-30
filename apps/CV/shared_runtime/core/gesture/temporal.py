"""Temporal gesture recognizers."""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque

from config import (
    GESTURE_STATIC_MAX_MOTION,
    GESTURE_STATIC_SETTLE_FRAMES,
    GESTURE_WAVE_MIN_FRAMES,
    GESTURE_WAVE_SETTLE_FRAMES,
)
from core.gesture.schemas import (
    GestureCandidate,
    HandLandmark,
    HandObservation,
    NO_GESTURE,
)

logger = logging.getLogger(__name__)


MOTION_LANDMARKS = (0, 4, 8, 12, 16, 20)


class StaticGestureStabilizer:
    """Stabilizes static gestures before allowing them to fire."""

    def __init__(
        self,
        settle_frames: int = GESTURE_STATIC_SETTLE_FRAMES,
        max_motion: float = GESTURE_STATIC_MAX_MOTION,
    ):
        self.settle_frames = max(1, settle_frames)
        self.max_motion = max_motion
        self._last_landmarks: dict[str, tuple[HandLandmark, ...]] = {}
        self._last_key: dict[str, str] = {}
        self._settled_frames: dict[str, int] = defaultdict(int)

    def update(
        self,
        observation: HandObservation,
        candidate: GestureCandidate,
    ) -> GestureCandidate:
        hand = observation.handedness
        previous_landmarks = self._last_landmarks.get(hand)
        motion = self._landmark_motion(previous_landmarks, observation.landmarks)
        self._last_landmarks[hand] = observation.landmarks

        if candidate.name == NO_GESTURE:
            self._reset(hand)
            return self._with_metadata(
                candidate,
                phase="none",
                motion=motion,
                settled_frames=0,
            )
        if candidate.name == "wave":
            self._reset(hand)
            return self._with_metadata(
                candidate,
                phase="moving",
                motion=motion,
                settled_frames=0,
            )
        if self.settle_frames <= 1:
            self._last_key[hand] = candidate.name
            self._settled_frames[hand] = 1
            logger.debug(
                "GESTURE 一帧静态判断: hand=%s gesture=%s motion=%.4f",
                hand,
                candidate.name,
                motion,
            )
            return self._with_metadata(
                candidate,
                phase="complete",
                motion=motion,
                settled_frames=1,
            )

        last_key = self._last_key.get(hand)
        if last_key != candidate.name:
            self._last_key[hand] = candidate.name
            self._settled_frames[hand] = 0
            phase = (
                "moving"
                if previous_landmarks is None or motion > self.max_motion
                else "settling"
            )
            return self._with_metadata(
                candidate,
                phase=phase,
                motion=motion,
                settled_frames=0,
            )

        if previous_landmarks is None or motion > self.max_motion:
            self._settled_frames[hand] = 0
            return self._with_metadata(
                candidate,
                phase="moving",
                motion=motion,
                settled_frames=0,
            )

        self._settled_frames[hand] += 1
        settled_frames = self._settled_frames[hand]
        phase = "complete" if settled_frames >= self.settle_frames else "settling"
        return self._with_metadata(
            candidate,
            phase=phase,
            motion=motion,
            settled_frames=settled_frames,
        )

    def remove_hand(self, hand: str) -> None:
        self._last_landmarks.pop(hand, None)
        self._last_key.pop(hand, None)
        self._settled_frames.pop(hand, None)

    def track_landmarks(self, observation: HandObservation) -> None:
        hand = observation.handedness
        self._last_landmarks[hand] = observation.landmarks
        self._reset(hand)

    def _reset(self, hand: str) -> None:
        self._last_key.pop(hand, None)
        self._settled_frames[hand] = 0

    def _with_metadata(
        self,
        candidate: GestureCandidate,
        *,
        phase: str,
        motion: float,
        settled_frames: int,
    ) -> GestureCandidate:
        metadata = dict(candidate.metadata or {})
        metadata.update(
            {
                "phase": phase,
                "motion": round(motion, 4),
                "settled_frames": settled_frames,
                "required_settle_frames": self.settle_frames,
            }
        )
        return GestureCandidate(
            name=candidate.name,
            confidence=candidate.confidence,
            hand=candidate.hand,
            metadata=metadata,
        )

    @staticmethod
    def _landmark_motion(
        previous: tuple[HandLandmark, ...] | None,
        current: tuple[HandLandmark, ...],
    ) -> float:
        if previous is None or len(previous) < 21 or len(current) < 21:
            return 1.0
        total = 0.0
        for index in MOTION_LANDMARKS:
            total += (
                (current[index].x - previous[index].x) ** 2
                + (current[index].y - previous[index].y) ** 2
            ) ** 0.5
        return total / len(MOTION_LANDMARKS)


class WaveGestureRecognizer:
    """Detects a completed wave after lateral movement settles."""

    def __init__(
        self,
        window_seconds: float = 1.8,
        min_frames: int = GESTURE_WAVE_MIN_FRAMES,
        settle_frames: int = GESTURE_WAVE_SETTLE_FRAMES,
        max_motion: float = GESTURE_STATIC_MAX_MOTION,
    ):
        self.window_seconds = window_seconds
        self.min_frames = max(3, min_frames)
        self.settle_frames = max(1, settle_frames)
        self.max_motion = max_motion
        self._history: dict[str, deque[tuple[float, float, float]]] = defaultdict(deque)
        self._settle_counts: dict[str, int] = defaultdict(int)
        self._entry_time: dict[str, float] = {}

    def update(
        self,
        observation: HandObservation,
        static_candidate: GestureCandidate,
    ) -> GestureCandidate | None:
        now = time.time()
        hand = observation.handedness
        wrist = observation.landmarks[0]
        history = self._history[hand]
        previous = history[-1] if history else None
        history.append((now, wrist.x, wrist.y))
        while history and now - history[0][0] > self.window_seconds:
            history.popleft()

        if len(history) < self.min_frames:
            return None
        if static_candidate.name != "open_hand":
            self._entry_time.pop(hand, None)
            return None

        xs = [item[1] for item in history]
        ys = [item[2] for item in history]
        x_range = max(xs) - min(xs)
        y_range = max(ys) - min(ys)
        if y_range > 0.25:
            return None

        turns = self._direction_turns(xs)

        if turns < 1:
            self._entry_time.pop(hand, None)
            return None

        if hand not in self._entry_time:
            self._entry_time[hand] = now
        wave_duration = now - self._entry_time[hand]
        if wave_duration < 0.5:
            return None

        x_motion = abs(wrist.x - previous[1]) if previous else 1.0
        if x_range < 0.08:
            return None

        if x_motion <= self.max_motion:
            self._settle_counts[hand] += 1
        else:
            self._settle_counts[hand] = 0

        phase = (
            "complete" if self._settle_counts[hand] >= self.settle_frames else "moving"
        )
        confidence = min(0.96, 0.72 + turns * 0.06 + x_range * 0.9)
        if phase != "complete":
            confidence = min(confidence, 0.82)

        return GestureCandidate(
            name="wave",
            confidence=round(confidence, 4),
            hand=hand,
            metadata={
                "phase": phase,
                "settled_frames": self._settle_counts[hand],
                "required_settle_frames": self.settle_frames,
                "required_wave_frames": self.min_frames,
                "turns": turns,
                "x_range": round(x_range, 4),
                "x_motion": round(x_motion, 4),
                "wave_duration": round(wave_duration, 3),
                "static": static_candidate.name,
            },
        )

    def remove_hand(self, hand: str) -> None:
        self._history.pop(hand, None)
        self._settle_counts.pop(hand, None)
        self._entry_time.pop(hand, None)

    @staticmethod
    def _direction_turns(values: list[float]) -> int:
        directions: list[int] = []
        previous = values[0]
        for value in values[1:]:
            delta = value - previous
            previous = value
            if abs(delta) < 0.025:
                continue
            direction = 1 if delta > 0 else -1
            if not directions or directions[-1] != direction:
                directions.append(direction)
        return max(0, len(directions) - 1)

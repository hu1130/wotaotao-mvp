"""Schemas shared by the gesture recognition pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class HandLandmark:
    x: float
    y: float
    z: float = 0.0


@dataclass(frozen=True)
class HandObservation:
    landmarks: tuple[HandLandmark, ...]
    handedness: str
    confidence: float


@dataclass(frozen=True)
class GestureCandidate:
    name: str
    confidence: float
    hand: str
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class GestureEvent:
    name: str
    confidence: float
    hand: str
    stage: str
    timestamp: float
    action_mode: str
    metadata: dict = field(default_factory=dict)


NO_GESTURE = "none"
FEATURE_VERSION = 2

THUMB_TIP = 4
INDEX_MCP = 5
MIDDLE_MCP = 9
PINKY_MCP = 17
FEATURE_DIM = 63
FEATURE_EPSILON = 1e-6


def observation_to_features(observation: HandObservation) -> list[float] | None:
    if len(observation.landmarks) < 21:
        return None
    wrist = observation.landmarks[0]
    thumb_tip = observation.landmarks[THUMB_TIP]
    index_mcp = observation.landmarks[INDEX_MCP]
    flip_x = (thumb_tip.x - index_mcp.x) > 0
    features = []
    for lm in observation.landmarks:
        dx = -(lm.x - wrist.x) if flip_x else (lm.x - wrist.x)
        features.extend([dx, lm.y - wrist.y, lm.z - wrist.z])
    return normalize_features(features)


def normalize_features(features: list[float]) -> list[float] | None:
    if len(features) != FEATURE_DIM:
        return None
    scale = _palm_scale(features)
    if scale <= FEATURE_EPSILON:
        return features
    return [float(value) / scale for value in features]


def _landmark_vector(features: list[float], index: int) -> tuple[float, float, float]:
    start = index * 3
    return features[start], features[start + 1], features[start + 2]


def _distance(
    a: tuple[float, float, float],
    b: tuple[float, float, float],
) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5


def _palm_scale(features: list[float]) -> float:
    wrist = _landmark_vector(features, 0)
    middle_mcp = _landmark_vector(features, MIDDLE_MCP)
    index_mcp = _landmark_vector(features, INDEX_MCP)
    pinky_mcp = _landmark_vector(features, PINKY_MCP)
    return max(
        _distance(wrist, middle_mcp),
        _distance(index_mcp, pinky_mcp),
        FEATURE_EPSILON,
    )

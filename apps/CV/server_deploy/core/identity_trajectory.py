"""Cross-track identity continuity based on recent face trajectories.

The camera tracker can allocate a new ``track_id`` after speech deformation,
brief blur, or a detector miss. This module reconnects that new track to a
recently confirmed identity only when temporal, spatial, size, and (for
multi-face frames) weak appearance evidence agree.
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass


@dataclass(frozen=True)
class FaceTrajectoryObservation:
    track_id: int
    bbox: tuple[int, int, int, int]
    recognized_name: str = ""
    similarity: float = 0.0
    nearest_name: str = ""

    @property
    def recognized(self) -> bool:
        return bool(self.recognized_name)


@dataclass(frozen=True)
class IdentityRecovery:
    track_id: int
    source_track_id: int
    name: str
    similarity: float
    score: float
    age_seconds: float


@dataclass
class _KnownTrajectory:
    name: str
    track_id: int
    bbox: tuple[int, int, int, int]
    similarity: float
    last_seen_at: float
    velocity_x: float = 0.0
    velocity_y: float = 0.0


class IdentityTrajectoryTracker:
    """Recovers known identities across short-lived tracker ID changes."""

    def __init__(
        self,
        *,
        max_gap_seconds: float = 3.0,
        retention_seconds: float = 10.0,
        min_nearest_similarity: float = 0.22,
    ) -> None:
        self.max_gap_seconds = max(0.5, float(max_gap_seconds))
        self.retention_seconds = max(self.max_gap_seconds, float(retention_seconds))
        self.min_nearest_similarity = max(0.0, float(min_nearest_similarity))
        self._by_device: dict[str, dict[str, _KnownTrajectory]] = {}
        self._lock = threading.RLock()

    def resolve(
        self,
        device_id: str,
        observations: list[FaceTrajectoryObservation],
        *,
        now: float,
    ) -> dict[int, IdentityRecovery]:
        device_key = (device_id or "default").strip()[:80] or "default"
        with self._lock:
            trajectories = self._by_device.setdefault(device_key, {})
            self._prune(trajectories, now)

            current_names = {
                observation.recognized_name
                for observation in observations
                if observation.recognized_name
            }
            for observation in observations:
                if observation.recognized:
                    self._update_trajectory(trajectories, observation, now)

            unknowns = [item for item in observations if not item.recognized]
            frame_face_count = len(observations)
            proposals: list[tuple[float, int, str, IdentityRecovery]] = []
            for observation in unknowns:
                for name, trajectory in trajectories.items():
                    if name in current_names:
                        # A confirmed face for this identity already exists in the
                        # frame, so another face must not inherit the same person.
                        continue
                    recovery = self._score_recovery(
                        observation,
                        trajectory,
                        now=now,
                        frame_face_count=frame_face_count,
                    )
                    if recovery is not None:
                        proposals.append((recovery.score, observation.track_id, name, recovery))

            proposals.sort(key=lambda item: item[0], reverse=True)
            assigned_tracks: set[int] = set()
            assigned_names: set[str] = set()
            recoveries: dict[int, IdentityRecovery] = {}
            for _, track_id, name, recovery in proposals:
                if track_id in assigned_tracks or name in assigned_names:
                    continue
                competing = [
                    item[3]
                    for item in proposals
                    if item[1] == track_id and item[2] != name
                ]
                if competing and recovery.score - competing[0].score < 0.12:
                    continue
                assigned_tracks.add(track_id)
                assigned_names.add(name)
                recoveries[track_id] = recovery
                source = trajectories[name]
                inherited = FaceTrajectoryObservation(
                    track_id=track_id,
                    bbox=next(
                        item.bbox for item in observations if item.track_id == track_id
                    ),
                    recognized_name=name,
                    similarity=source.similarity,
                    nearest_name=name,
                )
                self._update_trajectory(trajectories, inherited, now)
            return recoveries

    def clear_scope(self, scope_key: str) -> int:
        with self._lock:
            trajectories = self._by_device.pop(scope_key, None)
            return len(trajectories or {})

    def _score_recovery(
        self,
        observation: FaceTrajectoryObservation,
        trajectory: _KnownTrajectory,
        *,
        now: float,
        frame_face_count: int,
    ) -> IdentityRecovery | None:
        age = max(0.0, now - trajectory.last_seen_at)
        if age > self.max_gap_seconds:
            return None

        predicted_bbox = _shift_bbox(
            trajectory.bbox,
            trajectory.velocity_x * age,
            trajectory.velocity_y * age,
        )
        iou = _bbox_iou(predicted_bbox, observation.bbox)
        normalized_distance = _normalized_center_distance(
            predicted_bbox,
            observation.bbox,
        )
        area_ratio = _area_ratio(predicted_bbox, observation.bbox)
        appearance_support = (
            observation.nearest_name == trajectory.name
            and observation.similarity >= self.min_nearest_similarity
        )
        geometry_strong = iou >= 0.25 or normalized_distance <= 0.35
        geometry_loose = iou >= 0.08 or normalized_distance <= 0.65
        track_changed = observation.track_id != trajectory.track_id

        if area_ratio < 0.45:
            return None
        if (
            track_changed
            and not appearance_support
            and not (age <= 0.8 and iou >= 0.55 and normalized_distance <= 0.20)
        ):
            return None
        if frame_face_count <= 1:
            if not geometry_strong and not (geometry_loose and appearance_support):
                return None
        elif not (geometry_strong and appearance_support):
            return None

        center_score = max(0.0, 1.0 - normalized_distance)
        time_score = max(0.0, 1.0 - age / self.max_gap_seconds)
        appearance_score = observation.similarity if appearance_support else 0.0
        score = (
            0.35 * max(iou, center_score)
            + 0.25 * area_ratio
            + 0.20 * time_score
            + 0.20 * appearance_score
        )
        minimum_score = 0.58 if frame_face_count <= 1 else 0.66
        if score < minimum_score:
            return None
        return IdentityRecovery(
            track_id=observation.track_id,
            source_track_id=trajectory.track_id,
            name=trajectory.name,
            similarity=trajectory.similarity,
            score=score,
            age_seconds=age,
        )

    @staticmethod
    def _update_trajectory(
        trajectories: dict[str, _KnownTrajectory],
        observation: FaceTrajectoryObservation,
        now: float,
    ) -> None:
        previous = trajectories.get(observation.recognized_name)
        velocity_x = 0.0
        velocity_y = 0.0
        if previous is not None:
            elapsed = max(0.05, now - previous.last_seen_at)
            old_x, old_y = _bbox_center(previous.bbox)
            new_x, new_y = _bbox_center(observation.bbox)
            measured_x = (new_x - old_x) / elapsed
            measured_y = (new_y - old_y) / elapsed
            max_velocity = max(
                previous.bbox[2] - previous.bbox[0],
                previous.bbox[3] - previous.bbox[1],
                1,
            ) * 1.5
            measured_x = max(-max_velocity, min(max_velocity, measured_x))
            measured_y = max(-max_velocity, min(max_velocity, measured_y))
            velocity_x = previous.velocity_x * 0.6 + measured_x * 0.4
            velocity_y = previous.velocity_y * 0.6 + measured_y * 0.4
        trajectories[observation.recognized_name] = _KnownTrajectory(
            name=observation.recognized_name,
            track_id=observation.track_id,
            bbox=observation.bbox,
            similarity=max(
                observation.similarity,
                previous.similarity if previous is not None else 0.0,
            ),
            last_seen_at=now,
            velocity_x=velocity_x,
            velocity_y=velocity_y,
        )

    def _prune(self, trajectories: dict[str, _KnownTrajectory], now: float) -> None:
        for name, trajectory in list(trajectories.items()):
            if now - trajectory.last_seen_at > self.retention_seconds:
                trajectories.pop(name, None)


def _bbox_center(bbox: tuple[int, int, int, int]) -> tuple[float, float]:
    x1, y1, x2, y2 = bbox
    return (x1 + x2) / 2.0, (y1 + y2) / 2.0


def _bbox_area(bbox: tuple[int, int, int, int]) -> float:
    x1, y1, x2, y2 = bbox
    return float(max(0, x2 - x1) * max(0, y2 - y1))


def _bbox_iou(
    first: tuple[int, int, int, int],
    second: tuple[int, int, int, int],
) -> float:
    ax1, ay1, ax2, ay2 = first
    bx1, by1, bx2, by2 = second
    width = max(0, min(ax2, bx2) - max(ax1, bx1))
    height = max(0, min(ay2, by2) - max(ay1, by1))
    intersection = width * height
    union = _bbox_area(first) + _bbox_area(second) - intersection
    return intersection / union if union > 0 else 0.0


def _normalized_center_distance(
    first: tuple[int, int, int, int],
    second: tuple[int, int, int, int],
) -> float:
    first_x, first_y = _bbox_center(first)
    second_x, second_y = _bbox_center(second)
    distance = math.hypot(first_x - second_x, first_y - second_y)
    widths = [first[2] - first[0], second[2] - second[0]]
    heights = [first[3] - first[1], second[3] - second[1]]
    scale = max(*widths, *heights, 1)
    return distance / scale


def _area_ratio(
    first: tuple[int, int, int, int],
    second: tuple[int, int, int, int],
) -> float:
    first_area = _bbox_area(first)
    second_area = _bbox_area(second)
    largest = max(first_area, second_area)
    return min(first_area, second_area) / largest if largest > 0 else 0.0


def _shift_bbox(
    bbox: tuple[int, int, int, int],
    delta_x: float,
    delta_y: float,
) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = bbox
    return (
        int(round(x1 + delta_x)),
        int(round(y1 + delta_y)),
        int(round(x2 + delta_x)),
        int(round(y2 + delta_y)),
    )

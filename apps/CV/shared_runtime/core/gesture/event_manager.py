"""Gesture event stabilization and staged response policy."""

from __future__ import annotations

import time
import logging
from dataclasses import dataclass

from config import (
    GESTURE_CONFIRM_FRAMES,
    GESTURE_COOLDOWN_SECONDS,
    GESTURE_REQUIRE_RELEASE_BEFORE_REPEAT,
    GESTURE_STAGE,
)
from core.gesture.schemas import GestureCandidate, GestureEvent, NO_GESTURE

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GestureStagePolicy:
    key: str
    action_mode: str
    drives_avatar: bool
    description: str


STAGE_POLICIES = {
    "observe": GestureStagePolicy(
        key="observe",
        action_mode="observe_only",
        drives_avatar=False,
        description="只识别，写日志和调试状态，不驱动数字人",
    ),
    "idle": GestureStagePolicy(
        key="idle",
        action_mode="idle_response",
        drives_avatar=True,
        description="仅在数字人空闲时响应",
    ),
    "light": GestureStagePolicy(
        key="light",
        action_mode="light_response",
        drives_avatar=True,
        description="轻量回应，不打断说话",
    ),
    "full": GestureStagePolicy(
        key="full",
        action_mode="full_linkage",
        drives_avatar=True,
        description="完整动作和语音联动",
    ),
}


class GestureEventManager:
    """Turns noisy frame-level candidates into debounced gesture events."""

    def __init__(self, stage: str = GESTURE_STAGE) -> None:
        self.policy = STAGE_POLICIES.get(stage, STAGE_POLICIES["observe"])
        self._streak_key: tuple[str, str] | None = None
        self._streak_count = 0
        self._cooldowns: dict[tuple[str, str], float] = {}
        self._stable_candidate: GestureCandidate | None = None
        self._consumed_key: tuple[str, str] | None = None

    @property
    def stable_candidate(self) -> GestureCandidate | None:
        return self._stable_candidate

    def clear_hand(self, hand: str, reason: str = "") -> None:
        changed = False
        if self._stable_candidate and self._stable_candidate.hand == hand:
            self._stable_candidate = None
            changed = True
        if self._consumed_key and self._consumed_key[0] == hand:
            self._consumed_key = None
            changed = True
        if self._streak_key and self._streak_key[0] == hand:
            self._streak_key = None
            self._streak_count = 0
            changed = True
        if changed:
            logger.debug("GESTURE 清理手势状态: hand=%s reason=%s", hand, reason)

    def clear_all(self, reason: str = "") -> None:
        if self._stable_candidate or self._consumed_key or self._streak_key:
            logger.debug("GESTURE 清理全部手势状态: reason=%s", reason)
        self._streak_key = None
        self._streak_count = 0
        self._stable_candidate = None
        self._consumed_key = None

    def update(self, candidate: GestureCandidate) -> GestureEvent | None:
        now = time.time()
        self._cooldowns = {k: v for k, v in self._cooldowns.items() if v > now}
        is_ml = candidate.metadata and candidate.metadata.get("source") == "ml"
        phase = candidate.metadata.get("phase") if candidate.metadata else ""
        suppress_event = bool(
            candidate.metadata and candidate.metadata.get("suppress_event")
        )

        if candidate.name == NO_GESTURE:
            self.clear_hand(candidate.hand, "none")
            return None

        if suppress_event:
            if self._consumed_key and self._consumed_key[0] == candidate.hand:
                logger.debug(
                    "GESTURE 状态重置: hand=%s reason=suppress_event candidate=%s consumed=%s",
                    candidate.hand,
                    candidate.name,
                    self._consumed_key,
                )
                self._consumed_key = None
            self._streak_key = None
            self._streak_count = 0
            self._stable_candidate = None
            return None

        if phase in {"moving", "settling"}:
            if self._consumed_key and self._consumed_key[0] == candidate.hand:
                self._consumed_key = None
            if (
                self._stable_candidate
                and self._stable_candidate.hand == candidate.hand
            ):
                self._stable_candidate = None
            return None

        if candidate.name == "wave" and phase != "complete":
            return None

        key = (candidate.hand, candidate.name)
        if key == self._consumed_key:
            if GESTURE_REQUIRE_RELEASE_BEFORE_REPEAT:
                logger.debug(
                    "GESTURE 等待释放后重复触发: hand=%s gesture=%s",
                    candidate.hand,
                    candidate.name,
                )
                return None
            cooldown_until = self._cooldowns.get(key, 0.0)
            if now < cooldown_until:
                return None
            logger.debug(
                "GESTURE 已消费状态过期: hand=%s gesture=%s cooldown_expired_at=%.3f",
                candidate.hand,
                candidate.name,
                cooldown_until,
            )
            self._consumed_key = None

        if phase == "complete":
            if candidate.name != "wave" and not self._confirm_candidate(key):
                return None
            self._stable_candidate = candidate
            if now < self._cooldowns.get(key, 0.0):
                return None
            self._cooldowns[key] = now + GESTURE_COOLDOWN_SECONDS
            self._consumed_key = key
            return GestureEvent(
                name=candidate.name,
                confidence=candidate.confidence,
                hand=candidate.hand,
                stage=self.policy.key,
                timestamp=now,
                action_mode=self.policy.action_mode,
                metadata=candidate.metadata,
            )

        if is_ml:
            self._stable_candidate = candidate
            if now < self._cooldowns.get(key, 0.0):
                return None
            self._cooldowns[key] = now + GESTURE_COOLDOWN_SECONDS
            self._consumed_key = key
            return GestureEvent(
                name=candidate.name,
                confidence=candidate.confidence,
                hand=candidate.hand,
                stage=self.policy.key,
                timestamp=now,
                action_mode=self.policy.action_mode,
                metadata=candidate.metadata,
            )

        if key == self._streak_key:
            self._streak_count += 1
        else:
            self._streak_key = key
            self._streak_count = 1

        if self._streak_count < GESTURE_CONFIRM_FRAMES:
            return None
        self._stable_candidate = candidate
        if now < self._cooldowns.get(key, 0.0):
            return None

        self._cooldowns[key] = now + GESTURE_COOLDOWN_SECONDS
        self._consumed_key = key
        return GestureEvent(
            name=candidate.name,
            confidence=candidate.confidence,
            hand=candidate.hand,
            stage=self.policy.key,
            timestamp=now,
            action_mode=self.policy.action_mode,
            metadata=candidate.metadata,
        )

    def _confirm_candidate(self, key: tuple[str, str]) -> bool:
        if key == self._streak_key:
            self._streak_count += 1
        else:
            self._streak_key = key
            self._streak_count = 1
            logger.debug(
                "GESTURE 候选开始确认: hand=%s gesture=%s required_frames=%d",
                key[0],
                key[1],
                GESTURE_CONFIRM_FRAMES,
            )
        return self._streak_count >= GESTURE_CONFIRM_FRAMES

"""多帧投票: 连续 N 帧识别结果投票, 避免单帧误识别 (眨眼/侧脸/模糊/运动)"""

from __future__ import annotations

from collections import defaultdict, deque
import threading

from config import VOTE_WINDOW, VOTE_MIN_VOTES


class VoteBuffer:
    """多帧投票缓冲区。

    用法:
        buf = VoteBuffer(window=5, min_votes=3)
        voted_name = buf.vote(track_id, name, similarity, time.time())
        if voted_name is not None:
            check_in(voted_name)
    """

    def __init__(
        self,
        window: int = VOTE_WINDOW,
        min_votes: int = VOTE_MIN_VOTES,
        cooldown: float = 5.0,
    ):
        self._window = window
        self._min_votes = min_votes
        self._cooldown = cooldown
        self._buffers: dict[tuple[str, int], deque[tuple[str, float]]] = defaultdict(
            lambda: deque(maxlen=window)
        )
        self._confirmed: dict[tuple[str, int], tuple[str, float]] = {}
        self._lock = threading.RLock()

    def vote(
        self,
        track_id: int,
        name: str | None,
        similarity: float,
        now: float,
        *,
        scope_key: str = "default",
    ) -> str | None:
        cache_key = (scope_key, track_id)
        with self._lock:
            if cache_key in self._confirmed:
                confirmed_name, confirmed_time = self._confirmed[cache_key]
                if now - confirmed_time < self._cooldown:
                    return None
            key = "__UNKNOWN__" if name is None else name
            self._buffers[cache_key].append((key, similarity))
            buf = self._buffers[cache_key]
            if len(buf) < self._min_votes:
                return None
            counts: dict[str, int] = defaultdict(int)
            for voted_name, _ in buf:
                if voted_name != "__UNKNOWN__":
                    counts[voted_name] += 1
            if not counts:
                return None
            if key != "__UNKNOWN__" and counts[key] >= self._min_votes:
                self._confirmed[cache_key] = (key, now)
                return key
            return None

    def cleanup_inactive(
        self,
        active_track_ids: set[int],
        *,
        scope_key: str = "default",
    ) -> None:
        with self._lock:
            for cache_key in list(self._buffers.keys()):
                if cache_key[0] == scope_key and cache_key[1] not in active_track_ids:
                    self._buffers.pop(cache_key, None)
                    self._confirmed.pop(cache_key, None)

    def clear_name(self, name: str, tenant_id: str = "") -> None:
        tenant_prefix = f"tenant={tenant_id}|" if tenant_id else ""
        with self._lock:
            for cache_key, buffer in list(self._buffers.items()):
                if tenant_prefix and not cache_key[0].startswith(tenant_prefix):
                    continue
                filtered = [item for item in buffer if item[0] != name]
                if len(filtered) != len(buffer):
                    buffer.clear()
                    buffer.extend(filtered)
            for cache_key, (confirmed_name, _) in list(self._confirmed.items()):
                if confirmed_name == name and (
                    not tenant_prefix or cache_key[0].startswith(tenant_prefix)
                ):
                    self._confirmed.pop(cache_key, None)

    def clear_scope(self, scope_key: str) -> int:
        with self._lock:
            buffer_keys = [key for key in self._buffers if key[0] == scope_key]
            confirmed_keys = [key for key in self._confirmed if key[0] == scope_key]
            for key in buffer_keys:
                self._buffers.pop(key, None)
            for key in confirmed_keys:
                self._confirmed.pop(key, None)
            return len(buffer_keys) + len(confirmed_keys)

    def clear_all(self, tenant_id: str = "") -> int:
        with self._lock:
            if tenant_id:
                prefix = f"tenant={tenant_id}|"
                buffer_keys = [key for key in self._buffers if key[0].startswith(prefix)]
                confirmed_keys = [key for key in self._confirmed if key[0].startswith(prefix)]
                for key in buffer_keys:
                    self._buffers.pop(key, None)
                for key in confirmed_keys:
                    self._confirmed.pop(key, None)
                return len(buffer_keys) + len(confirmed_keys)
            count = len(self._buffers) + len(self._confirmed)
            self._buffers.clear()
            self._confirmed.clear()
            return count

"""Legacy SSE session limiter (SPEC §15.4 / §12 / Step 12)."""

from __future__ import annotations

import time
from collections.abc import Callable


class LegacySessionLimiter:
    """Bound active SSE sessions; support idle eviction and touch."""

    def __init__(
        self,
        *,
        max_sessions: int,
        idle_timeout_seconds: int,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if max_sessions < 1:
            raise ValueError("max_sessions must be >= 1")
        if idle_timeout_seconds < 1:
            raise ValueError("idle_timeout_seconds must be >= 1")
        self._max = max_sessions
        self._idle = idle_timeout_seconds
        self._clock = clock or time.monotonic
        self._last_touch: dict[str, float] = {}

    def try_open(self, session_id: str) -> bool:
        if session_id in self._last_touch:
            self.touch(session_id)
            return True
        if len(self._last_touch) >= self._max:
            return False
        self._last_touch[session_id] = self._clock()
        return True

    def close(self, session_id: str) -> None:
        self._last_touch.pop(session_id, None)

    def touch(self, session_id: str) -> None:
        if session_id in self._last_touch:
            self._last_touch[session_id] = self._clock()

    def evict_idle(self) -> tuple[str, ...]:
        now = self._clock()
        expired = tuple(
            sid
            for sid, touched in self._last_touch.items()
            if now - touched >= self._idle
        )
        for sid in expired:
            self._last_touch.pop(sid, None)
        return expired

    def active_count(self) -> int:
        return len(self._last_touch)

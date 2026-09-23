"""Fixed clock for demo agent (SPEC §8.6 / 「本周」解析)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FixedClock:
    """Deterministic UTC clock for tests and reproducible demos."""

    now_utc: str

    def now(self) -> str:
        return self.now_utc

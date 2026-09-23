"""MCP query latency / RSS baseline helpers (SPEC §16.4).

Thresholds are hard ceilings — do not relax. Live measurement is SMOKE.
"""

from __future__ import annotations

import math
from typing import Mapping, Sequence

P95_QUERY_MS_MAX = 800
P99_QUERY_MS_MAX = 1500
RSS_MB_MAX = 256
RSS_GROWTH_MB_MAX_AFTER_100 = 20
MIN_LATENCY_SAMPLES = 20


def _percentile(sorted_samples: Sequence[float], pct: float) -> float:
    if not sorted_samples:
        raise ValueError("empty samples")
    n = len(sorted_samples)
    # Nearest-rank: ceil(pct/100 * n), 1-indexed → 0-indexed
    rank = max(1, min(n, int(math.ceil((pct / 100.0) * n))))
    return float(sorted_samples[rank - 1])


def evaluate_latency_ms(samples: Sequence[float]) -> dict[str, object]:
    """Evaluate server-side query latencies against §16.4 (no model time)."""
    values = [float(x) for x in samples]
    n = len(values)
    if n < MIN_LATENCY_SAMPLES:
        return {
            "ok": False,
            "reason": "insufficient samples for P95/P99",
            "samples": n,
            "p95_ms": None,
            "p99_ms": None,
        }
    ordered = sorted(values)
    p95 = _percentile(ordered, 95)
    p99 = _percentile(ordered, 99)
    ok = p95 <= P95_QUERY_MS_MAX and p99 <= P99_QUERY_MS_MAX
    reason = "within thresholds" if ok else "latency exceeds SPEC section 16.4 ceiling"
    return {
        "ok": ok,
        "reason": reason,
        "samples": n,
        "p95_ms": p95,
        "p99_ms": p99,
    }


def evaluate_rss_mb(
    *,
    steady_rss_mb: float,
    growth_after_100_queries_mb: float,
) -> Mapping[str, object]:
    ok = (
        steady_rss_mb <= RSS_MB_MAX
        and growth_after_100_queries_mb <= RSS_GROWTH_MB_MAX_AFTER_100
    )
    return {
        "ok": ok,
        "steady_rss_mb": steady_rss_mb,
        "growth_after_100_queries_mb": growth_after_100_queries_mb,
    }

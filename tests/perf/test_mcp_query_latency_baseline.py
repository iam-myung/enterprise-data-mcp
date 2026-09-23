"""RED: MCP query latency / RSS baseline shell (SPEC §16.4 / Step 14).

Must not lower thresholds. Perf module must exist before release.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PERF_PATH = PROJECT_ROOT / "scripts" / "perf_baseline.py"

# SPEC §16.4 hard ceilings — GREEN must not weaken these constants.
P95_MS_MAX = 800
P99_MS_MAX = 1500
RSS_MB_MAX = 256
RSS_GROWTH_MB_MAX_AFTER_100 = 20
MIN_LATENCY_SAMPLES = 20


def _perf() -> Any:
    import scripts.perf_baseline as perf_baseline

    return perf_baseline


def test_perf_baseline_script_exists() -> None:
    assert PERF_PATH.is_file(), "expected scripts/perf_baseline.py"


def test_perf_baseline_thresholds_match_spec_16_4() -> None:
    perf = _perf()
    assert int(perf.P95_QUERY_MS_MAX) == P95_MS_MAX
    assert int(perf.P99_QUERY_MS_MAX) == P99_MS_MAX
    assert int(perf.RSS_MB_MAX) == RSS_MB_MAX
    assert int(perf.RSS_GROWTH_MB_MAX_AFTER_100) == RSS_GROWTH_MB_MAX_AFTER_100
    assert int(perf.MIN_LATENCY_SAMPLES) >= MIN_LATENCY_SAMPLES


def test_perf_baseline_thresholds_are_not_relaxed() -> None:
    perf = _perf()
    assert int(perf.P95_QUERY_MS_MAX) <= P95_MS_MAX
    assert int(perf.P99_QUERY_MS_MAX) <= P99_MS_MAX
    assert int(perf.RSS_MB_MAX) <= RSS_MB_MAX
    assert int(perf.RSS_GROWTH_MB_MAX_AFTER_100) <= RSS_GROWTH_MB_MAX_AFTER_100


def test_perf_baseline_evaluate_rejects_single_sample_as_p95() -> None:
    perf = _perf()
    report = perf.evaluate_latency_ms([10])  # single sample must not claim P95 pass
    assert report["ok"] is False
    assert "sample" in str(report.get("reason", "")).lower() or int(
        report.get("samples", 0)
    ) < MIN_LATENCY_SAMPLES


def test_perf_baseline_evaluate_fails_when_p95_exceeds_ceiling() -> None:
    perf = _perf()
    # 20 samples all at 900ms → P95 >= 900 > 800
    samples = [900] * MIN_LATENCY_SAMPLES
    report = perf.evaluate_latency_ms(samples)
    assert report["ok"] is False
    assert float(report["p95_ms"]) > P95_MS_MAX

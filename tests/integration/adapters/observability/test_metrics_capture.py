"""RED: real Prometheus registry capture of a metric sample (SPEC §16.3 / Step 8.3).

No production PrometheusMetricsAdapter until 8.3-GREEN.
"""

from __future__ import annotations

from typing import Any


def _adapter() -> Any:
    from enterprise_data_mcp.adapters.observability.prometheus_metrics_adapter import (
        PrometheusMetricsAdapter,
    )

    return PrometheusMetricsAdapter()


def test_registry_captures_metric_sample_without_high_cardinality_labels() -> None:
    adapter = _adapter()
    adapter.record_metric(
        "mcp_requests_total",
        1.0,
        {
            "operation": "query_data",
            "status": "SUCCEEDED",
            "transport": "stdio",
            "caller_id": "should-not-leak",
            "sql": "SELECT 1",
        },
    )

    getter = getattr(adapter, "generate_latest", None)
    assert callable(getter), "Adapter must expose generate_latest() for real capture"
    raw = getter()
    text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)

    assert "mcp_requests_total" in text
    assert 'operation="query_data"' in text
    assert 'status="SUCCEEDED"' in text
    assert 'transport="stdio"' in text
    assert 'caller_id="' not in text
    assert 'sql="' not in text
    assert "should-not-leak" not in text
    assert "SELECT 1" not in text

    # No HTTP /metrics Host side effects required for this smoke path.
    shutdown = getattr(adapter, "shutdown", None)
    if callable(shutdown):
        shutdown()

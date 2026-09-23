"""RED: Prometheus Metrics Adapter — §16.3 names + high-cardinality label ban (Step 8.3).

No production PrometheusMetricsAdapter until 8.3-GREEN.
"""

from __future__ import annotations

from typing import Any

import pytest

_METRIC_NAMES: frozenset[str] = frozenset(
    {
        "mcp_requests_total",
        "mcp_request_duration_ms",
        "query_rows_returned",
        "query_rejections_total",
        "audit_write_failures_total",
        "active_mcp_connections",
        "mcp_inflight_requests",
    }
)

# Low-cardinality label keys allowed across §16.3 declarations.
_ALLOWED_LABEL_KEYS: frozenset[str] = frozenset(
    {
        "operation",
        "status",
        "transport",
        "dataset",
        "error_code",
    }
)

_FORBIDDEN_LABEL_KEYS: frozenset[str] = frozenset(
    {
        "caller_id",
        "sql",
        "password",
        "secret",
        "query_value",
    }
)


def _adapter_cls() -> Any:
    from enterprise_data_mcp.adapters.observability.prometheus_metrics_adapter import (
        PrometheusMetricsAdapter,
    )

    return PrometheusMetricsAdapter


def _metric_names() -> frozenset[str]:
    from enterprise_data_mcp.adapters.observability.metric_names import (
        METRIC_NAMES,
    )

    return frozenset(METRIC_NAMES)


def _allowed_label_keys() -> frozenset[str]:
    from enterprise_data_mcp.adapters.observability.metric_names import (
        ALLOWED_LABEL_KEYS,
    )

    return frozenset(ALLOWED_LABEL_KEYS)


def _exposition(adapter: Any) -> str:
    getter = getattr(adapter, "generate_latest", None)
    assert callable(getter), "Adapter must expose generate_latest() for capture"
    raw = getter()
    if isinstance(raw, bytes):
        return raw.decode("utf-8")
    return str(raw)


def test_prometheus_metrics_adapter_importable() -> None:
    cls = _adapter_cls()
    assert callable(getattr(cls, "record_metric", None)) or hasattr(
        cls, "record_metric"
    )


def test_metric_names_closure_matches_spec_16_3() -> None:
    names = _metric_names()
    assert names == _METRIC_NAMES
    assert len(names) == 7


def test_allowed_label_keys_are_low_cardinality_only() -> None:
    keys = _allowed_label_keys()
    assert keys == _ALLOWED_LABEL_KEYS
    for forbidden in _FORBIDDEN_LABEL_KEYS:
        assert forbidden not in keys


@pytest.mark.parametrize("metric_name", sorted(_METRIC_NAMES))
def test_each_metric_name_can_be_recorded(metric_name: str) -> None:
    adapter = _adapter_cls()()
    labels = _minimal_labels_for(metric_name)
    adapter.record_metric(metric_name, 1.0, labels)
    text = _exposition(adapter)
    assert metric_name in text


def test_unknown_metric_name_is_silently_dropped() -> None:
    """Align with 8.1 whitelist style: unknown names must not appear."""
    adapter = _adapter_cls()()
    adapter.record_metric("not_a_spec_metric", 1.0, {"operation": "x"})
    text = _exposition(adapter)
    assert "not_a_spec_metric" not in text


def test_high_cardinality_label_keys_never_appear_in_exposition() -> None:
    adapter = _adapter_cls()()
    adapter.record_metric(
        "mcp_requests_total",
        1.0,
        {
            "operation": "query_data",
            "status": "SUCCEEDED",
            "transport": "stdio",
            "caller_id": "user-42",
            "sql": "SELECT * FROM users",
            "password": "s3cret",
            "query_value": "alice@example.com",
        },
    )
    text = _exposition(adapter)
    # Forbidden keys must not appear as label names in exposition.
    assert 'caller_id="' not in text
    assert 'sql="' not in text
    assert 'password="' not in text
    assert 'query_value="' not in text
    # Forbidden values must not leak as label values either.
    assert "user-42" not in text
    assert "SELECT * FROM users" not in text
    assert "s3cret" not in text
    assert "alice@example.com" not in text
    # Allowed labels must remain.
    assert 'operation="query_data"' in text
    assert 'status="SUCCEEDED"' in text
    assert 'transport="stdio"' in text


def test_forbidden_label_keys_not_in_allowed_closure() -> None:
    """Port may receive high-cardinality keys; closure must not admit them."""
    keys = _allowed_label_keys()
    for forbidden in _FORBIDDEN_LABEL_KEYS:
        assert forbidden not in keys
        assert forbidden not in _ALLOWED_LABEL_KEYS


def _minimal_labels_for(metric_name: str) -> dict[str, str]:
    if metric_name == "mcp_requests_total":
        return {
            "operation": "query_data",
            "status": "SUCCEEDED",
            "transport": "stdio",
        }
    if metric_name == "mcp_request_duration_ms":
        return {"operation": "query_data"}
    if metric_name == "query_rows_returned":
        return {"dataset": "sales_inventory_daily"}
    if metric_name == "query_rejections_total":
        return {"error_code": "DATASET_NOT_ALLOWED"}
    if metric_name == "audit_write_failures_total":
        return {}
    if metric_name == "active_mcp_connections":
        return {"transport": "stdio"}
    if metric_name == "mcp_inflight_requests":
        return {"transport": "stdio"}
    return {}

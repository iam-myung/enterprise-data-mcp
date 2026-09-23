"""RED: OTEL Trace Adapter — critical spans + parent/child TraceID (SPEC §16.2 / Step 8.2).

No production OtelTraceAdapter until 8.2-GREEN.
"""

from __future__ import annotations

from typing import Any

import pytest

_CRITICAL_SPANS: frozenset[str] = frozenset(
    {
        "mcp.request",
        "policy.check",
        "catalog.read",
        "query.compile",
        "mysql.execute",
        "audit.write",
    }
)

# 32-char hex TraceId (OTEL wire format); logical id shared across parent/child.
_TRACE_ID = "0123456789abcdef0123456789abcdef"


def _adapter_cls() -> Any:
    from enterprise_data_mcp.adapters.observability.otel_trace_adapter import (
        OtelTraceAdapter,
    )

    return OtelTraceAdapter


def _critical_names() -> frozenset[str]:
    from enterprise_data_mcp.adapters.observability.span_names import (
        CRITICAL_SPAN_NAMES,
    )

    return frozenset(CRITICAL_SPAN_NAMES)


def _finished_spans(adapter: Any) -> list[Any]:
    flush = getattr(adapter, "force_flush", None)
    if callable(flush):
        flush()
    getter = getattr(adapter, "get_finished_spans", None)
    assert callable(getter), "Adapter must expose get_finished_spans() for capture"
    spans = list(getter())
    return spans


def test_otel_trace_adapter_importable() -> None:
    cls = _adapter_cls()
    assert callable(getattr(cls, "start_span", None)) or hasattr(cls, "start_span")


def test_critical_span_names_closure_matches_spec_16_2() -> None:
    names = _critical_names()
    assert names == _CRITICAL_SPANS
    # No extras, no typos.
    assert len(names) == 6


def test_same_trace_id_parent_child_spans_are_recoverable() -> None:
    adapter = _adapter_cls()()
    adapter.start_span(_TRACE_ID, "mcp.request")
    adapter.start_span(_TRACE_ID, "policy.check")
    # Adapter-only end to export finished spans (Port has start_span only).
    end = getattr(adapter, "end_span", None)
    assert callable(end), "Adapter must expose end_span(trace_id) to close nested spans"
    end(_TRACE_ID)  # child
    end(_TRACE_ID)  # parent

    spans = _finished_spans(adapter)
    by_name = {s.name: s for s in spans}
    assert "mcp.request" in by_name
    assert "policy.check" in by_name
    parent = by_name["mcp.request"]
    child = by_name["policy.check"]

    parent_tid = format(parent.context.trace_id, "032x")
    child_tid = format(child.context.trace_id, "032x")
    assert parent_tid == child_tid
    assert parent_tid == _TRACE_ID
    assert child.parent is not None
    assert child.parent.span_id == parent.context.span_id


@pytest.mark.parametrize("span_name", sorted(_CRITICAL_SPANS))
def test_each_critical_span_name_can_be_started(span_name: str) -> None:
    adapter = _adapter_cls()()
    tid = "fedcba9876543210fedcba9876543210"
    adapter.start_span(tid, span_name)
    end = getattr(adapter, "end_span", None)
    assert callable(end)
    end(tid)
    spans = _finished_spans(adapter)
    assert any(s.name == span_name for s in spans)


def test_non_critical_operation_name_is_not_in_closure() -> None:
    """Port may accept business operation names; they must not dilute §16.2 closure."""
    assert "query_data" not in _critical_names()
    assert "query_data" not in _CRITICAL_SPANS


def test_span_attributes_must_not_leak_sql_or_secrets() -> None:
    adapter = _adapter_cls()()
    adapter.start_span(_TRACE_ID, "mysql.execute")
    # record_event may attach fields; forbidden keys/values must not land on span.
    record = getattr(adapter, "record_event", None)
    assert callable(record)
    record(
        _TRACE_ID,
        "query.detail",
        {
            "sql": "SELECT * FROM users",
            "password": "s3cret",
            "dataset_id": "sales_inventory_daily",
        },
    )
    end = getattr(adapter, "end_span", None)
    assert callable(end)
    end(_TRACE_ID)
    spans = _finished_spans(adapter)
    assert spans, "expected at least one finished span"
    blob = " ".join(
        f"{s.name} {getattr(s, 'attributes', None)} {getattr(s, 'events', None)}"
        for s in spans
    ).lower()
    assert "select * from users" not in blob
    assert "s3cret" not in blob
    assert "password" not in blob
    # Key name "sql" must not appear as an attribute key.
    for s in spans:
        attrs = dict(getattr(s, "attributes", None) or {})
        assert "sql" not in attrs
        assert "password" not in attrs

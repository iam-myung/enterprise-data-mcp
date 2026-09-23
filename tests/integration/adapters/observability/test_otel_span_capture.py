"""RED: real InMemory capture of OTEL parent/child spans (SPEC §16.2 / Step 8.2).

No production OtelTraceAdapter until 8.2-GREEN.
"""

from __future__ import annotations

from typing import Any

_TRACE_ID = "0123456789abcdef0123456789abcdef"


def _adapter() -> Any:
    from enterprise_data_mcp.adapters.observability.otel_trace_adapter import (
        OtelTraceAdapter,
    )

    return OtelTraceAdapter()


def test_inmemory_exporter_captures_parent_child_critical_spans() -> None:
    adapter = _adapter()
    adapter.start_span(_TRACE_ID, "mcp.request")
    adapter.start_span(_TRACE_ID, "catalog.read")
    end = getattr(adapter, "end_span", None)
    assert callable(end), "Adapter must expose end_span(trace_id)"
    end(_TRACE_ID)
    end(_TRACE_ID)

    flush = getattr(adapter, "force_flush", None)
    if callable(flush):
        flush()
    getter = getattr(adapter, "get_finished_spans", None)
    assert callable(getter)
    spans = list(getter())
    assert len(spans) >= 2, "expected real InMemory capture of >=2 finished spans"

    by_name = {s.name: s for s in spans}
    assert "mcp.request" in by_name
    assert "catalog.read" in by_name
    parent = by_name["mcp.request"]
    child = by_name["catalog.read"]

    assert format(parent.context.trace_id, "032x") == _TRACE_ID
    assert format(child.context.trace_id, "032x") == _TRACE_ID
    assert child.parent is not None
    assert child.parent.span_id == parent.context.span_id

    # No OTLP / network side effects required for this smoke path.
    shutdown = getattr(adapter, "shutdown", None)
    if callable(shutdown):
        shutdown()

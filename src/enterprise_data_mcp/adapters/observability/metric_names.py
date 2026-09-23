"""Prometheus metric name / label closures (SPEC §16.3 / Step 8.3)."""

from __future__ import annotations

METRIC_NAMES: frozenset[str] = frozenset(
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

ALLOWED_LABEL_KEYS: frozenset[str] = frozenset(
    {
        "operation",
        "status",
        "transport",
        "dataset",
        "error_code",
    }
)

# Per-metric labelnames from SPEC §16.3 declarations.
METRIC_LABELNAMES: dict[str, tuple[str, ...]] = {
    "mcp_requests_total": ("operation", "status", "transport"),
    "mcp_request_duration_ms": ("operation",),
    "query_rows_returned": ("dataset",),
    "query_rejections_total": ("error_code",),
    "audit_write_failures_total": (),
    "active_mcp_connections": ("transport",),
    "mcp_inflight_requests": ("transport",),
}

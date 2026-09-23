"""Prometheus Metrics Adapter — label-whitelisted record_metric (SPEC §16.3).

Isolated CollectorRegistry; unknown metric names dropped; high-cardinality
labels stripped. No MCP Host /metrics endpoint.
"""

from __future__ import annotations

from typing import Mapping

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

from enterprise_data_mcp.adapters.observability.metric_names import (
    ALLOWED_LABEL_KEYS,
    METRIC_LABELNAMES,
    METRIC_NAMES,
)


class PrometheusMetricsAdapter:
    """Per-instance registry; TelemetryPort.record_metric surface only."""

    def __init__(self) -> None:
        self._registry = CollectorRegistry(auto_describe=True)
        self._counters: dict[str, Counter] = {}
        self._histograms: dict[str, Histogram] = {}
        self._gauges: dict[str, Gauge] = {}
        self._register_instruments()

    def record_metric(
        self, name: str, value: float, labels: Mapping[str, object]
    ) -> None:
        if name not in METRIC_NAMES:
            return
        safe = {
            key: str(val)
            for key, val in labels.items()
            if key in ALLOWED_LABEL_KEYS
        }
        labelnames = METRIC_LABELNAMES[name]
        label_values = tuple(safe.get(key, "") for key in labelnames)

        if name in self._counters:
            counter = self._counters[name]
            if labelnames:
                counter.labels(*label_values).inc(value)
            else:
                counter.inc(value)
            return
        if name in self._histograms:
            self._histograms[name].labels(*label_values).observe(value)
            return
        if name in self._gauges:
            self._gauges[name].labels(*label_values).set(value)

    def generate_latest(self) -> bytes:
        return generate_latest(self._registry)

    def shutdown(self) -> None:
        # Registry is process-local; drop references for cleanup clarity.
        self._counters.clear()
        self._histograms.clear()
        self._gauges.clear()

    def _register_instruments(self) -> None:
        self._counters["mcp_requests_total"] = Counter(
            "mcp_requests_total",
            "MCP request count",
            labelnames=METRIC_LABELNAMES["mcp_requests_total"],
            registry=self._registry,
        )
        self._histograms["mcp_request_duration_ms"] = Histogram(
            "mcp_request_duration_ms",
            "MCP request duration in milliseconds",
            labelnames=METRIC_LABELNAMES["mcp_request_duration_ms"],
            registry=self._registry,
        )
        self._counters["query_rows_returned"] = Counter(
            "query_rows_returned",
            "Rows returned by authorized queries",
            labelnames=METRIC_LABELNAMES["query_rows_returned"],
            registry=self._registry,
        )
        self._counters["query_rejections_total"] = Counter(
            "query_rejections_total",
            "Query rejections by error code",
            labelnames=METRIC_LABELNAMES["query_rejections_total"],
            registry=self._registry,
        )
        self._counters["audit_write_failures_total"] = Counter(
            "audit_write_failures_total",
            "Audit write failures",
            labelnames=METRIC_LABELNAMES["audit_write_failures_total"],
            registry=self._registry,
        )
        self._gauges["active_mcp_connections"] = Gauge(
            "active_mcp_connections",
            "Active MCP connections",
            labelnames=METRIC_LABELNAMES["active_mcp_connections"],
            registry=self._registry,
        )
        self._gauges["mcp_inflight_requests"] = Gauge(
            "mcp_inflight_requests",
            "In-flight MCP requests",
            labelnames=METRIC_LABELNAMES["mcp_inflight_requests"],
            registry=self._registry,
        )

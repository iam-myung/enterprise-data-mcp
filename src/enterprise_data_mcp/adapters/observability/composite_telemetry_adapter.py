"""Composite TelemetryPort — OTel + Prometheus + JSON log (SPEC §16 / BUG-04)."""

from __future__ import annotations

import io
from collections.abc import Mapping
from typing import Any, TextIO

from enterprise_data_mcp.adapters.observability.json_logger import StructuredJsonLogger
from enterprise_data_mcp.adapters.observability.otel_trace_adapter import (
    OtelTraceAdapter,
)
from enterprise_data_mcp.adapters.observability.prometheus_metrics_adapter import (
    PrometheusMetricsAdapter,
)


class CompositeTelemetryAdapter:
    """Fan-out TelemetryPort for Live MySQL container wiring."""

    def __init__(self, *, log_stream: TextIO | None = None) -> None:
        self._otel = OtelTraceAdapter()
        self._metrics = PrometheusMetricsAdapter()
        self._logger = StructuredJsonLogger()
        self.log_stream: TextIO = log_stream if log_stream is not None else io.StringIO()

    def start_span(self, trace_id: str, operation: str) -> None:
        self._otel.start_span(trace_id, operation)

    def end_span(self, trace_id: str) -> None:
        self._otel.end_span(trace_id)

    def record_event(
        self, trace_id: str, event: str, fields: Mapping[str, object]
    ) -> None:
        self._otel.record_event(trace_id, event, fields)

    def record_metric(
        self, name: str, value: float, labels: Mapping[str, object]
    ) -> None:
        self._metrics.record_metric(name, value, labels)

    def emit_log(self, **kwargs: Any) -> None:
        self._logger.emit(stream=self.log_stream, **kwargs)

    def get_finished_spans(self) -> list:
        return self._otel.get_finished_spans()

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        return self._otel.force_flush(timeout_millis)

    def generate_latest(self) -> bytes:
        return self._metrics.generate_latest()

    def shutdown(self) -> None:
        self._otel.shutdown()
        self._metrics.shutdown()

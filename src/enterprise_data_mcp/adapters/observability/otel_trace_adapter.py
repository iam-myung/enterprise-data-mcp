"""OTEL Trace Adapter — InMemory spans with recoverable parent/child (SPEC §16.2).

Implements TelemetryPort start_span / record_event. record_metric is a no-op
until Step 8.3. No Host wiring.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Mapping

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.sdk.trace.id_generator import RandomIdGenerator
from opentelemetry.trace import (
    NonRecordingSpan,
    Span,
    SpanContext,
    TraceFlags,
    TraceState,
    set_span_in_context,
)

# Align with structured-log extras (8.1); drop secrets/SQL/PII keys.
_ALLOWED_EVENT_KEYS: frozenset[str] = frozenset(
    {
        "dataset_id",
        "error_code",
        "row_count",
        "transport",
        "audit_stage",
    }
)

_id_gen = RandomIdGenerator()


class OtelTraceAdapter:
    """Per-instance TracerProvider + InMemory exporter; stack per TraceID."""

    def __init__(self) -> None:
        self._exporter = InMemorySpanExporter()
        self._provider = TracerProvider()
        self._provider.add_span_processor(SimpleSpanProcessor(self._exporter))
        self._tracer = self._provider.get_tracer("enterprise_data_mcp.otel")
        self._stacks: dict[str, list[Span]] = defaultdict(list)

    def start_span(self, trace_id: str, operation: str) -> None:
        stack = self._stacks[trace_id]
        if stack:
            context = set_span_in_context(stack[-1])
        else:
            context = _seed_trace_context(trace_id)
        span = self._tracer.start_span(operation, context=context)
        stack.append(span)

    def end_span(self, trace_id: str) -> None:
        stack = self._stacks[trace_id]
        if not stack:
            raise RuntimeError(f"no open span for trace_id={trace_id!r}")
        span = stack.pop()
        span.end()
        if not stack:
            del self._stacks[trace_id]

    def record_event(
        self, trace_id: str, event: str, fields: Mapping[str, object]
    ) -> None:
        stack = self._stacks.get(trace_id)
        if not stack:
            return
        safe = {
            key: value
            for key, value in fields.items()
            if key in _ALLOWED_EVENT_KEYS and _is_otel_attr_value(value)
        }
        stack[-1].add_event(event, attributes=safe)

    def record_metric(
        self, name: str, value: float, labels: Mapping[str, object]
    ) -> None:
        # Step 8.3 owns Metrics; keep Protocol surface only.
        return None

    def get_finished_spans(self) -> list:
        return list(self._exporter.get_finished_spans())

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        return bool(self._provider.force_flush(timeout_millis))

    def shutdown(self) -> None:
        self._provider.shutdown()


def _seed_trace_context(trace_id_hex: str):
    """Inject caller TraceID via remote NonRecording parent (not a real span)."""
    span_context = SpanContext(
        trace_id=int(trace_id_hex, 16),
        span_id=_id_gen.generate_span_id(),
        is_remote=True,
        trace_flags=TraceFlags(TraceFlags.SAMPLED),
        trace_state=TraceState(),
    )
    return set_span_in_context(NonRecordingSpan(span_context))


def _is_otel_attr_value(value: object) -> bool:
    return isinstance(value, (bool, int, float, str))

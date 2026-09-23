"""ExecuteReadQuery application use case (SPEC §9.3 / §4.4 / Step 5.2).

Fake-port driven. No MySQL / MCP Host I/O.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from enterprise_data_mcp.application.ports import (
    AuditPort,
    CatalogPort,
    ClockPort,
    IdPort,
    PolicyPort,
    QueryPort,
    TelemetryPort,
)
from enterprise_data_mcp.domain.errors import AuditStatus, ErrorCode
from enterprise_data_mcp.domain.models import (
    AuditRecord,
    CallerContext,
    DatasetPolicy,
    EnvelopeMeta,
    ErrorInfo,
    FieldSummary,
    OperationEnvelope,
    QueryPlan,
    QueryResult,
)
from enterprise_data_mcp.domain.rules import (
    DomainRuleError,
    FieldRuleMeta,
    validate_query_request,
)

_OPERATION = "query_data"
_DEFAULT_LIMIT = 50
_MAX_LIMIT = 100


class ExecuteReadQuery:
    def __init__(
        self,
        *,
        policy: PolicyPort,
        catalog: CatalogPort,
        query: QueryPort,
        audit: AuditPort,
        telemetry: TelemetryPort,
        clock: ClockPort,
        ids: IdPort,
    ) -> None:
        self._policy = policy
        self._catalog = catalog
        self._query = query
        self._audit = audit
        self._telemetry = telemetry
        self._clock = clock
        self._ids = ids

    def execute(
        self,
        *,
        caller: CallerContext,
        call_id: str,
        request: Mapping[str, object],
    ) -> OperationEnvelope[QueryResult] | OperationEnvelope[None]:
        started_at = self._clock.now_utc()
        trace_id = self._ids.new_trace_id()
        self._telemetry.start_span(trace_id, _OPERATION)

        dataset_hint = _dataset_hint(request)
        started = AuditRecord(
            call_id=call_id,
            trace_id=trace_id,
            caller=caller.caller_id,
            operation=_OPERATION,
            dataset=dataset_hint,
            status=AuditStatus.STARTED,
            timestamp=started_at,
            duration=0,
            error_code=None,
        )
        try:
            self._audit.start(started)
        except Exception:
            return self._audit_unavailable(
                trace_id=trace_id,
                started_at=started_at,
                audit_stage="start",
            )

        policies = self._policy.list_dataset_policies(caller)
        matched = next(
            (p for p in policies if p.dataset_id == dataset_hint), None
        )
        if matched is None:
            return self._reject(
                caller=caller,
                call_id=call_id,
                trace_id=trace_id,
                dataset_id=dataset_hint or "",
                started_at=started_at,
                code=ErrorCode.DATASET_NOT_ALLOWED,
                message="Dataset not allowed",
                context={"dataset_id": dataset_hint or ""},
            )

        snapshot = self._catalog.get_field_snapshot(matched)
        field_meta = _build_field_meta(matched, snapshot)

        try:
            validated = validate_query_request(
                request,
                allowed_fields=field_meta,
                default_limit=_DEFAULT_LIMIT,
                max_limit=_MAX_LIMIT,
            )
        except DomainRuleError as exc:
            return self._reject(
                caller=caller,
                call_id=call_id,
                trace_id=trace_id,
                dataset_id=matched.dataset_id,
                started_at=started_at,
                code=ErrorCode(exc.code),
                message=exc.message,
                context=exc.context,
            )

        plan = _to_query_plan(matched, validated)
        result, duration_ms = self._query.execute(plan)

        finished_at = self._clock.now_utc()
        finished = AuditRecord(
            call_id=call_id,
            trace_id=trace_id,
            caller=caller.caller_id,
            operation=_OPERATION,
            dataset=matched.dataset_id,
            status=AuditStatus.SUCCEEDED,
            timestamp=finished_at,
            duration=duration_ms,
            error_code=None,
        )
        try:
            self._audit.finish(finished)
        except Exception:
            return self._audit_unavailable(
                trace_id=trace_id,
                started_at=started_at,
                audit_stage="finish",
            )

        self._emit_query_telemetry(
            caller=caller,
            trace_id=trace_id,
            finished_at=finished_at,
            status="SUCCEEDED",
            duration_ms=duration_ms,
            dataset_id=matched.dataset_id,
            row_count=result.row_count,
            error_code=None,
        )

        return OperationEnvelope.ok(
            result,
            EnvelopeMeta(
                trace_id=trace_id,
                timestamp_utc=finished_at,
                operation=_OPERATION,
                duration_ms=duration_ms,
            ),
        )

    def _reject(
        self,
        *,
        caller: CallerContext,
        call_id: str,
        trace_id: str,
        dataset_id: str,
        started_at: str,
        code: ErrorCode,
        message: str,
        context: Mapping[str, object],
    ) -> OperationEnvelope[None]:
        finished_at = self._clock.now_utc()
        finished = AuditRecord(
            call_id=call_id,
            trace_id=trace_id,
            caller=caller.caller_id,
            operation=_OPERATION,
            dataset=dataset_id,
            status=AuditStatus.REJECTED,
            timestamp=finished_at,
            duration=0,
            error_code=code.value,
        )
        try:
            self._audit.finish(finished)
        except Exception:
            return self._audit_unavailable(
                trace_id=trace_id,
                started_at=started_at,
                audit_stage="finish",
            )

        self._emit_query_telemetry(
            caller=caller,
            trace_id=trace_id,
            finished_at=finished_at,
            status="REJECTED",
            duration_ms=0,
            dataset_id=dataset_id,
            row_count=0,
            error_code=code.value,
        )

        return OperationEnvelope.fail(
            ErrorInfo(code=code.value, message=message, context=dict(context)),
            EnvelopeMeta(
                trace_id=trace_id,
                timestamp_utc=finished_at,
                operation=_OPERATION,
                duration_ms=0,
            ),
        )

    def _audit_unavailable(
        self, *, trace_id: str, started_at: str, audit_stage: str
    ) -> OperationEnvelope[None]:
        end = getattr(self._telemetry, "end_span", None)
        if callable(end):
            try:
                end(trace_id)
            except Exception:  # noqa: BLE001
                pass
        return OperationEnvelope.fail(
            ErrorInfo(
                code=ErrorCode.AUDIT_UNAVAILABLE.value,
                message="Audit unavailable",
                context={"audit_stage": audit_stage},
            ),
            EnvelopeMeta(
                trace_id=trace_id,
                timestamp_utc=started_at,
                operation=_OPERATION,
                duration_ms=0,
            ),
        )

    def _emit_query_telemetry(
        self,
        *,
        caller: CallerContext,
        trace_id: str,
        finished_at: str,
        status: str,
        duration_ms: int,
        dataset_id: str,
        row_count: int,
        error_code: str | None,
    ) -> None:
        transport = (
            caller.transport.value
            if hasattr(caller.transport, "value")
            else str(caller.transport)
        )
        self._telemetry.record_metric(
            "mcp_requests_total",
            1.0,
            {
                "operation": _OPERATION,
                "status": status,
                "transport": transport,
            },
        )
        self._telemetry.record_metric(
            "mcp_request_duration_ms",
            float(duration_ms),
            {"operation": _OPERATION},
        )
        if status == "SUCCEEDED":
            self._telemetry.record_metric(
                "query_rows_returned",
                float(row_count),
                {"dataset": dataset_id},
            )
        elif error_code:
            self._telemetry.record_metric(
                "query_rejections_total",
                1.0,
                {"error_code": error_code},
            )

        self._telemetry.record_event(
            trace_id,
            "query_finished",
            {
                "dataset_id": dataset_id,
                "error_code": error_code or "",
                "row_count": row_count,
                "transport": transport,
            },
        )
        end = getattr(self._telemetry, "end_span", None)
        if callable(end):
            end(trace_id)

        emit = getattr(self._telemetry, "emit_log", None)
        if callable(emit):
            payload: dict[str, object] = {
                "timestamp_utc": finished_at,
                "level": "INFO",
                "event": "query_finished",
                "trace_id": trace_id,
                "operation": _OPERATION,
                "status": status,
                "duration_ms": duration_ms,
            }
            if dataset_id:
                payload["dataset_id"] = dataset_id
            if error_code:
                payload["error_code"] = error_code
            if status == "SUCCEEDED":
                payload["row_count"] = row_count
            payload["transport"] = transport
            emit(**payload)


def _dataset_hint(request: Mapping[str, object]) -> str:
    raw = request.get("dataset_id", "")
    return raw if isinstance(raw, str) else ""


def _build_field_meta(
    policy: DatasetPolicy, snapshot: tuple[FieldSummary, ...]
) -> dict[str, FieldRuleMeta]:
    allowed = frozenset(policy.allowed_fields)
    meta: dict[str, FieldRuleMeta] = {}
    for field in snapshot:
        if field.field_id not in allowed:
            continue
        meta[field.field_id] = FieldRuleMeta(
            value_type=field.value_type,
            filterable=field.filterable,
            aggregatable=field.aggregatable,
            sortable=field.sortable,
        )
    return meta


def _to_query_plan(policy: DatasetPolicy, validated: Any) -> QueryPlan:
    if validated.projection:
        physical_projection = validated.projection
    else:
        physical_projection = tuple(
            [*validated.group_by, *(a.alias for a in validated.aggregations)]
        )
    bind_values: list[object] = []
    for filt in validated.filters:
        if filt.value is None:
            continue
        if isinstance(filt.value, tuple):
            bind_values.extend(filt.value)
        else:
            bind_values.append(filt.value)
    return QueryPlan(
        dataset_id=policy.dataset_id,
        physical_table=policy.physical_table,
        physical_projection=physical_projection,
        filters=validated.filters,
        aggregations=validated.aggregations,
        group_by=validated.group_by,
        order_by=validated.order_by,
        bind_values=tuple(bind_values),
        limit=validated.limit,
    )

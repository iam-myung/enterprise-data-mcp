"""Catalog application use cases (SPEC §9.1–§9.2 / Steps 3.2–3.3).

Fake-port driven. No YAML / MySQL / Host I/O.
"""

from __future__ import annotations

from dataclasses import dataclass

from enterprise_data_mcp.application.ports import (
    AuditPort,
    CatalogPort,
    ClockPort,
    IdPort,
    PolicyPort,
    TelemetryPort,
)
from enterprise_data_mcp.domain.errors import AuditStatus, ErrorCode, FilterOperator
from enterprise_data_mcp.domain.models import (
    AuditRecord,
    CallerContext,
    DatasetPolicy,
    DatasetSummary,
    EnvelopeMeta,
    ErrorInfo,
    FieldSummary,
    OperationEnvelope,
)

_LIST_OPERATION = "list_authorized_datasets"
_SCHEMA_OPERATION = "get_authorized_schema"
_DEFAULT_LIMIT = 50
_MAX_LIMIT = 100
_ALL_FILTER_OPERATORS: tuple[str, ...] = tuple(op.value for op in FilterOperator)


@dataclass(frozen=True, slots=True)
class DatasetList:
    datasets: tuple[DatasetSummary, ...]
    count: int


@dataclass(frozen=True, slots=True)
class DatasetSchema:
    dataset: DatasetSummary
    fields: tuple[FieldSummary, ...]
    default_limit: int
    max_limit: int
    allowed_filter_operators: tuple[str, ...]


class ListAuthorizedDatasets:
    def __init__(
        self,
        *,
        policy: PolicyPort,
        catalog: CatalogPort,
        audit: AuditPort,
        telemetry: TelemetryPort,
        clock: ClockPort,
        ids: IdPort,
    ) -> None:
        self._policy = policy
        self._catalog = catalog
        self._audit = audit
        self._telemetry = telemetry
        self._clock = clock
        self._ids = ids

    def execute(
        self, *, caller: CallerContext, call_id: str
    ) -> OperationEnvelope[DatasetList] | OperationEnvelope[None]:
        started_at = self._clock.now_utc()
        trace_id = self._ids.new_trace_id()
        self._telemetry.start_span(trace_id, _LIST_OPERATION)

        started = AuditRecord(
            call_id=call_id,
            trace_id=trace_id,
            caller=caller.caller_id,
            operation=_LIST_OPERATION,
            dataset="",
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
        summaries = self._intersect_summaries(policies)

        data = DatasetList(datasets=summaries, count=len(summaries))
        finished_at = self._clock.now_utc()
        finished = AuditRecord(
            call_id=call_id,
            trace_id=trace_id,
            caller=caller.caller_id,
            operation=_LIST_OPERATION,
            dataset="",
            status=AuditStatus.SUCCEEDED,
            timestamp=finished_at,
            duration=0,
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

        return OperationEnvelope.ok(
            data,
            EnvelopeMeta(
                trace_id=trace_id,
                timestamp_utc=finished_at,
                operation=_LIST_OPERATION,
                duration_ms=0,
            ),
        )

    def _intersect_summaries(
        self, policies: frozenset[DatasetPolicy]
    ) -> tuple[DatasetSummary, ...]:
        out: list[DatasetSummary] = []
        for policy in policies:
            snapshot = self._catalog.get_field_snapshot(policy)
            allowed = frozenset(policy.allowed_fields)
            if not any(field.field_id in allowed for field in snapshot):
                continue
            out.append(
                DatasetSummary(
                    dataset_id=policy.dataset_id,
                    title=policy.dataset_id,
                    description="",
                    capabilities=policy.capabilities,
                )
            )
        return tuple(out)

    def _audit_unavailable(
        self, *, trace_id: str, started_at: str, audit_stage: str
    ) -> OperationEnvelope[None]:
        return OperationEnvelope.fail(
            ErrorInfo(
                code=ErrorCode.AUDIT_UNAVAILABLE.value,
                message="Audit unavailable",
                context={"audit_stage": audit_stage},
            ),
            EnvelopeMeta(
                trace_id=trace_id,
                timestamp_utc=started_at,
                operation=_LIST_OPERATION,
                duration_ms=0,
            ),
        )


class GetAuthorizedSchema:
    def __init__(
        self,
        *,
        policy: PolicyPort,
        catalog: CatalogPort,
        audit: AuditPort,
        telemetry: TelemetryPort,
        clock: ClockPort,
        ids: IdPort,
    ) -> None:
        self._policy = policy
        self._catalog = catalog
        self._audit = audit
        self._telemetry = telemetry
        self._clock = clock
        self._ids = ids

    def execute(
        self, *, caller: CallerContext, call_id: str, dataset_id: str
    ) -> OperationEnvelope[DatasetSchema] | OperationEnvelope[None]:
        started_at = self._clock.now_utc()
        trace_id = self._ids.new_trace_id()
        self._telemetry.start_span(trace_id, _SCHEMA_OPERATION)

        started = AuditRecord(
            call_id=call_id,
            trace_id=trace_id,
            caller=caller.caller_id,
            operation=_SCHEMA_OPERATION,
            dataset=dataset_id,
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
        matched = next((p for p in policies if p.dataset_id == dataset_id), None)
        if matched is None:
            return self._reject_not_allowed(
                caller=caller,
                call_id=call_id,
                trace_id=trace_id,
                dataset_id=dataset_id,
                started_at=started_at,
            )

        snapshot = self._catalog.get_field_snapshot(matched)
        allowed = frozenset(matched.allowed_fields)
        fields = tuple(f for f in snapshot if f.field_id in allowed)
        if not fields:
            return self._reject_not_allowed(
                caller=caller,
                call_id=call_id,
                trace_id=trace_id,
                dataset_id=dataset_id,
                started_at=started_at,
            )

        data = DatasetSchema(
            dataset=DatasetSummary(
                dataset_id=matched.dataset_id,
                title=matched.dataset_id,
                description="",
                capabilities=matched.capabilities,
            ),
            fields=fields,
            default_limit=_DEFAULT_LIMIT,
            max_limit=_MAX_LIMIT,
            allowed_filter_operators=_ALL_FILTER_OPERATORS,
        )
        finished_at = self._clock.now_utc()
        finished = AuditRecord(
            call_id=call_id,
            trace_id=trace_id,
            caller=caller.caller_id,
            operation=_SCHEMA_OPERATION,
            dataset=dataset_id,
            status=AuditStatus.SUCCEEDED,
            timestamp=finished_at,
            duration=0,
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

        return OperationEnvelope.ok(
            data,
            EnvelopeMeta(
                trace_id=trace_id,
                timestamp_utc=finished_at,
                operation=_SCHEMA_OPERATION,
                duration_ms=0,
            ),
        )

    def _reject_not_allowed(
        self,
        *,
        caller: CallerContext,
        call_id: str,
        trace_id: str,
        dataset_id: str,
        started_at: str,
    ) -> OperationEnvelope[None]:
        finished_at = self._clock.now_utc()
        finished = AuditRecord(
            call_id=call_id,
            trace_id=trace_id,
            caller=caller.caller_id,
            operation=_SCHEMA_OPERATION,
            dataset=dataset_id,
            status=AuditStatus.REJECTED,
            timestamp=finished_at,
            duration=0,
            error_code=ErrorCode.DATASET_NOT_ALLOWED.value,
        )
        try:
            self._audit.finish(finished)
        except Exception:
            return self._audit_unavailable(
                trace_id=trace_id,
                started_at=started_at,
                audit_stage="finish",
            )

        return OperationEnvelope.fail(
            ErrorInfo(
                code=ErrorCode.DATASET_NOT_ALLOWED.value,
                message="Dataset not allowed",
                context={"dataset_id": dataset_id},
            ),
            EnvelopeMeta(
                trace_id=trace_id,
                timestamp_utc=finished_at,
                operation=_SCHEMA_OPERATION,
                duration_ms=0,
            ),
        )

    def _audit_unavailable(
        self, *, trace_id: str, started_at: str, audit_stage: str
    ) -> OperationEnvelope[None]:
        return OperationEnvelope.fail(
            ErrorInfo(
                code=ErrorCode.AUDIT_UNAVAILABLE.value,
                message="Audit unavailable",
                context={"audit_stage": audit_stage},
            ),
            EnvelopeMeta(
                trace_id=trace_id,
                timestamp_utc=started_at,
                operation=_SCHEMA_OPERATION,
                duration_ms=0,
            ),
        )

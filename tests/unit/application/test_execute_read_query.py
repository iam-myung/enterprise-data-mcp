"""RED: ExecuteReadQuery use case (SPEC §9.3 / §4.4 / Step 5.2).

Fake ports only. No production query_service until GREEN.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from enterprise_data_mcp.domain.errors import (
    AuditStatus,
    ErrorCode,
    ResultStatus,
    TransportKind,
)
from enterprise_data_mcp.domain.models import (
    AuditRecord,
    CallerContext,
    Capability,
    DatasetPolicy,
    FieldSummary,
    QueryPlan,
    QueryResult,
    QueryResultSource,
    ValueType,
)

_CALL_ID = "call-query-0001"
_TRACE_ID = "trace-query-aaaa-bbbb-cccc-dddd"
_TIMESTAMP_UTC = "2026-09-13T14:00:00Z"
_OPERATION = "query_data"
_CALLER_ID = "demo-stdio-client"
_POLICY_PROFILE = "demo_readonly"
_DATASET = "sales_inventory_daily"
_PHYSICAL = "v_sales_inventory_daily"


# ---------------------------------------------------------------------------
# Deterministic fake ports
# ---------------------------------------------------------------------------


@dataclass
class CallLog:
    events: list[str] = field(default_factory=list)

    def add(self, event: str) -> None:
        self.events.append(event)


@dataclass
class FakeClockPort:
    now: str = _TIMESTAMP_UTC

    def now_utc(self) -> str:
        return self.now


@dataclass
class FakeIdPort:
    trace_id: str = _TRACE_ID

    def new_trace_id(self) -> str:
        return self.trace_id


@dataclass
class FakeTelemetryPort:
    log: CallLog

    def start_span(self, trace_id: str, operation: str) -> None:
        self.log.add(f"telemetry.start_span:{operation}")

    def record_event(
        self, trace_id: str, event: str, fields: Mapping[str, object]
    ) -> None:
        self.log.add(f"telemetry.record_event:{event}")

    def record_metric(
        self, name: str, value: float, labels: Mapping[str, object]
    ) -> None:
        self.log.add(f"telemetry.record_metric:{name}")


@dataclass
class FakeAuditPort:
    log: CallLog
    fail_start: bool = False
    fail_finish: bool = False
    started: list[AuditRecord] = field(default_factory=list)
    finished: list[AuditRecord] = field(default_factory=list)

    def start(self, record: AuditRecord) -> None:
        self.log.add("audit.start")
        self.started.append(record)
        if self.fail_start:
            raise RuntimeError("audit start persistence failed")

    def finish(self, record: AuditRecord) -> None:
        self.log.add("audit.finish")
        self.finished.append(record)
        if self.fail_finish:
            raise RuntimeError("audit finish persistence failed")


@dataclass
class FakePolicyPort:
    log: CallLog
    policies: frozenset[DatasetPolicy]

    def list_dataset_policies(self, caller: CallerContext) -> frozenset[DatasetPolicy]:
        self.log.add("policy.list_dataset_policies")
        return self.policies


@dataclass
class FakeCatalogPort:
    log: CallLog
    snapshots: dict[str, tuple[FieldSummary, ...]]

    def get_field_snapshot(
        self, authorized: DatasetPolicy
    ) -> tuple[FieldSummary, ...]:
        self.log.add(f"catalog.get_field_snapshot:{authorized.dataset_id}")
        return self.snapshots[authorized.dataset_id]


@dataclass
class FakeQueryPort:
    log: CallLog
    result: QueryResult
    duration_ms: int = 12
    plans: list[QueryPlan] = field(default_factory=list)
    raise_exc: Exception | None = None

    def execute(self, plan: QueryPlan) -> tuple[QueryResult, int]:
        self.log.add("query.execute")
        self.plans.append(plan)
        if self.raise_exc is not None:
            raise self.raise_exc
        return self.result, self.duration_ms


def _field(
    field_id: str,
    value_type: ValueType,
    *,
    filterable: bool = True,
    aggregatable: bool = True,
    sortable: bool = True,
) -> FieldSummary:
    return FieldSummary(
        field_id=field_id,
        title=field_id,
        value_type=value_type,
        nullable=True,
        filterable=filterable,
        aggregatable=aggregatable,
        sortable=sortable,
    )


def _caller() -> CallerContext:
    return CallerContext(
        caller_id=_CALLER_ID,
        policy_profile=_POLICY_PROFILE,
        transport=TransportKind.STDIO,
    )


def _sales_policy() -> DatasetPolicy:
    return DatasetPolicy(
        dataset_id=_DATASET,
        physical_table=_PHYSICAL,
        allowed_fields=("product_id", "product_name", "units_sold", "category"),
        capabilities=(
            Capability.READ_DETAIL,
            Capability.FILTER,
            Capability.AGGREGATE,
        ),
    )


def _sales_snapshot() -> tuple[FieldSummary, ...]:
    return (
        _field("product_id", ValueType.STRING),
        _field("product_name", ValueType.STRING),
        _field("units_sold", ValueType.INTEGER),
        _field("category", ValueType.STRING),
        _field("secret_col", ValueType.STRING),  # not in policy
    )


def _ok_result() -> QueryResult:
    return QueryResult(
        result_status=ResultStatus.NON_EMPTY,
        columns=("product_id", "units_sold"),
        rows=(("p1", 3),),
        row_count=1,
        truncated=False,
        source=QueryResultSource(
            dataset_id=_DATASET, queried_at_utc=_TIMESTAMP_UTC
        ),
    )


def _detail_payload(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "dataset_id": _DATASET,
        "projection": ["product_id", "units_sold"],
        "filters": [],
        "aggregations": [],
        "group_by": [],
        "order_by": [],
        "limit": 10,
    }
    base.update(overrides)
    return base


def _load_use_case() -> Any:
    """Import production symbol under test (must fail until 5.2-GREEN)."""
    from enterprise_data_mcp.application.query_service import ExecuteReadQuery

    return ExecuteReadQuery


def _build(
    *,
    policies: frozenset[DatasetPolicy] | None = None,
    snapshots: dict[str, tuple[FieldSummary, ...]] | None = None,
    fail_start: bool = False,
    fail_finish: bool = False,
    query_result: QueryResult | None = None,
) -> tuple[Any, CallLog, FakeAuditPort, FakeQueryPort]:
    ExecuteReadQuery = _load_use_case()
    log = CallLog()
    audit = FakeAuditPort(log=log, fail_start=fail_start, fail_finish=fail_finish)
    query = FakeQueryPort(log=log, result=query_result or _ok_result())
    uc = ExecuteReadQuery(
        policy=FakePolicyPort(
            log=log, policies=policies if policies is not None else frozenset({_sales_policy()})
        ),
        catalog=FakeCatalogPort(
            log=log,
            snapshots=snapshots
            if snapshots is not None
            else {_DATASET: _sales_snapshot()},
        ),
        query=query,
        audit=audit,
        telemetry=FakeTelemetryPort(log=log),
        clock=FakeClockPort(),
        ids=FakeIdPort(),
    )
    return uc, log, audit, query


# ---------------------------------------------------------------------------
# Surface / happy path / ordering
# ---------------------------------------------------------------------------


def test_execute_read_query_is_importable() -> None:
    cls = _load_use_case()
    assert cls is not None
    assert callable(getattr(cls, "execute", None)) or hasattr(cls, "execute")


def test_happy_path_returns_query_result_envelope() -> None:
    uc, log, audit, query = _build()
    envelope = uc.execute(
        caller=_caller(), call_id=_CALL_ID, request=_detail_payload()
    )

    assert envelope.success is True
    assert envelope.error is None
    assert envelope.data is not None
    assert isinstance(envelope.data, QueryResult)
    assert envelope.data.row_count == 1
    assert envelope.meta.operation == _OPERATION
    assert envelope.meta.trace_id == _TRACE_ID
    assert audit.finished[0].status == AuditStatus.SUCCEEDED
    assert len(query.plans) == 1
    plan = query.plans[0]
    assert plan.dataset_id == _DATASET
    assert plan.physical_table == _PHYSICAL
    assert "product_id" in plan.physical_projection


def test_call_order_started_before_policy_catalog_query_before_finish() -> None:
    uc, log, _, _ = _build()
    uc.execute(caller=_caller(), call_id=_CALL_ID, request=_detail_payload())

    events = log.events
    assert events.index("audit.start") < events.index("policy.list_dataset_policies")
    assert events.index("policy.list_dataset_policies") < events.index(
        f"catalog.get_field_snapshot:{_DATASET}"
    )
    assert events.index(f"catalog.get_field_snapshot:{_DATASET}") < events.index(
        "query.execute"
    )
    assert events.index("query.execute") < events.index("audit.finish")


# ---------------------------------------------------------------------------
# Audit gate
# ---------------------------------------------------------------------------


def test_started_audit_failure_rejects_without_policy_or_query() -> None:
    uc, log, _, query = _build(fail_start=True)
    envelope = uc.execute(
        caller=_caller(), call_id=_CALL_ID, request=_detail_payload()
    )

    assert envelope.success is False
    assert envelope.data is None
    assert envelope.error is not None
    assert envelope.error.code == ErrorCode.AUDIT_UNAVAILABLE.value
    assert envelope.error.context == {"audit_stage": "start"}
    assert "policy.list_dataset_policies" not in log.events
    assert "query.execute" not in log.events
    assert query.plans == []


def test_finish_audit_failure_discards_query_result() -> None:
    uc, _, _, query = _build(fail_finish=True)
    envelope = uc.execute(
        caller=_caller(), call_id=_CALL_ID, request=_detail_payload()
    )

    assert len(query.plans) == 1  # query ran
    assert envelope.success is False
    assert envelope.data is None  # result discarded
    assert envelope.error is not None
    assert envelope.error.code == ErrorCode.AUDIT_UNAVAILABLE.value
    assert envelope.error.context == {"audit_stage": "finish"}


# ---------------------------------------------------------------------------
# Authorization / rules mapping
# ---------------------------------------------------------------------------


def test_unauthorized_dataset_returns_dataset_not_allowed() -> None:
    uc, log, audit, query = _build(policies=frozenset())
    envelope = uc.execute(
        caller=_caller(),
        call_id=_CALL_ID,
        request=_detail_payload(dataset_id="hr_secret"),
    )

    assert envelope.success is False
    assert envelope.error is not None
    assert envelope.error.code == ErrorCode.DATASET_NOT_ALLOWED.value
    assert envelope.error.context == {"dataset_id": "hr_secret"}
    assert "query.execute" not in log.events
    assert query.plans == []
    assert audit.finished[0].status == AuditStatus.REJECTED


def test_write_intent_maps_write_operation_forbidden() -> None:
    uc, log, audit, query = _build()
    envelope = uc.execute(
        caller=_caller(),
        call_id=_CALL_ID,
        request=_detail_payload(raw_sql="SELECT 1"),
    )

    assert envelope.success is False
    assert envelope.error is not None
    assert envelope.error.code == ErrorCode.WRITE_OPERATION_FORBIDDEN.value
    assert set(envelope.error.context.keys()) <= {"operation"}
    assert "SELECT " not in envelope.error.message
    assert "query.execute" not in log.events
    assert query.plans == []
    assert audit.finished[0].status == AuditStatus.REJECTED


def test_limit_above_max_maps_result_limit_exceeded() -> None:
    uc, log, _, query = _build()
    envelope = uc.execute(
        caller=_caller(),
        call_id=_CALL_ID,
        request=_detail_payload(limit=101),
    )

    assert envelope.success is False
    assert envelope.error is not None
    assert envelope.error.code == ErrorCode.RESULT_LIMIT_EXCEEDED.value
    assert set(envelope.error.context.keys()) <= {"requested_limit", "max_limit"}
    assert "query.execute" not in log.events
    assert query.plans == []


def test_envelope_never_exposes_physical_table_in_data() -> None:
    uc, _, _, _ = _build()
    envelope = uc.execute(
        caller=_caller(), call_id=_CALL_ID, request=_detail_payload()
    )
    assert envelope.success is True
    blob = repr(envelope.data)
    assert _PHYSICAL not in blob
    assert "phys_" not in blob.lower()

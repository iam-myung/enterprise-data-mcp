"""RED: ListAuthorizedDatasets use case (SPEC §9.1 / Step 3.2).

Fake ports only. No production catalog_service until GREEN.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from enterprise_data_mcp.domain.errors import (
    AuditStatus,
    ErrorCode,
    TransportKind,
)
from enterprise_data_mcp.domain.models import (
    AuditRecord,
    CallerContext,
    Capability,
    DatasetPolicy,
    DatasetSummary,
    FieldSummary,
    ValueType,
)

# Fixed fixtures — deterministic, not wall-clock.
_CALL_ID = "call-list-0001"
_TRACE_ID = "trace-list-aaaa-bbbb-cccc-dddd"
_TIMESTAMP_UTC = "2026-09-13T10:00:00Z"
_OPERATION = "list_authorized_datasets"
_CALLER_ID = "demo-stdio-client"
_POLICY_PROFILE = "demo_readonly"

_PHYSICAL_SALES = "phys_sales_secret"
_PHYSICAL_HR = "phys_hr_secret"
_PHYSICAL_GHOST = "phys_ghost_secret"


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
    spans: list[tuple[str, str]] = field(default_factory=list)
    events: list[tuple[str, str, Mapping[str, object]]] = field(default_factory=list)
    metrics: list[tuple[str, float, Mapping[str, object]]] = field(default_factory=list)

    def start_span(self, trace_id: str, operation: str) -> None:
        self.log.add("telemetry.start_span")
        self.spans.append((trace_id, operation))

    def record_event(
        self, trace_id: str, event: str, fields: Mapping[str, object]
    ) -> None:
        self.log.add(f"telemetry.record_event:{event}")
        self.events.append((trace_id, event, fields))

    def record_metric(
        self, name: str, value: float, labels: Mapping[str, object]
    ) -> None:
        self.log.add(f"telemetry.record_metric:{name}")
        self.metrics.append((name, value, labels))


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
    calls: list[CallerContext] = field(default_factory=list)

    def list_dataset_policies(self, caller: CallerContext) -> frozenset[DatasetPolicy]:
        self.log.add("policy.list_dataset_policies")
        self.calls.append(caller)
        return self.policies


@dataclass
class FakeCatalogPort:
    log: CallLog
    snapshots: dict[str, tuple[FieldSummary, ...]]
    calls: list[DatasetPolicy] = field(default_factory=list)

    def get_field_snapshot(
        self, authorized: DatasetPolicy
    ) -> tuple[FieldSummary, ...]:
        self.log.add(f"catalog.get_field_snapshot:{authorized.dataset_id}")
        self.calls.append(authorized)
        return self.snapshots[authorized.dataset_id]


def _field(
    field_id: str,
    *,
    filterable: bool = True,
    aggregatable: bool = False,
    sortable: bool = True,
) -> FieldSummary:
    return FieldSummary(
        field_id=field_id,
        title=field_id,
        value_type=ValueType.STRING,
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


def _policy(
    dataset_id: str,
    physical_table: str,
    allowed_fields: tuple[str, ...],
    capabilities: tuple[Capability, ...] = (Capability.READ_DETAIL, Capability.FILTER),
) -> DatasetPolicy:
    return DatasetPolicy(
        dataset_id=dataset_id,
        physical_table=physical_table,
        allowed_fields=allowed_fields,
        capabilities=capabilities,
    )


def _load_use_case() -> Any:
    """Import production symbols under test (must fail until 3.2-GREEN)."""
    from enterprise_data_mcp.application.catalog_service import (
        DatasetList,
        ListAuthorizedDatasets,
    )

    return DatasetList, ListAuthorizedDatasets


def _build_use_case(
    *,
    policies: frozenset[DatasetPolicy],
    snapshots: dict[str, tuple[FieldSummary, ...]],
    fail_start: bool = False,
    fail_finish: bool = False,
) -> tuple[Any, CallLog, FakePolicyPort, FakeCatalogPort, FakeAuditPort]:
    DatasetList, ListAuthorizedDatasets = _load_use_case()
    log = CallLog()
    policy = FakePolicyPort(log=log, policies=policies)
    catalog = FakeCatalogPort(log=log, snapshots=snapshots)
    audit = FakeAuditPort(log=log, fail_start=fail_start, fail_finish=fail_finish)
    telemetry = FakeTelemetryPort(log=log)
    clock = FakeClockPort()
    ids = FakeIdPort()
    use_case = ListAuthorizedDatasets(
        policy=policy,
        catalog=catalog,
        audit=audit,
        telemetry=telemetry,
        clock=clock,
        ids=ids,
    )
    return use_case, log, policy, catalog, audit


# ---------------------------------------------------------------------------
# Happy path — authorized intersection summaries only
# ---------------------------------------------------------------------------


def test_happy_path_returns_only_policy_catalog_intersection_summaries() -> None:
    sales = _policy("sales", _PHYSICAL_SALES, ("amount", "region"))
    hr = _policy("hr", _PHYSICAL_HR, ("salary",))
    ghost = _policy("ghost", _PHYSICAL_GHOST, ("id",))

    use_case, log, policy, catalog, audit = _build_use_case(
        policies=frozenset({sales, hr, ghost}),
        snapshots={
            # amount ∩ allowed → keep; leak_col not in policy → ignored
            "sales": (_field("amount"), _field("leak_col")),
            # no overlap with allowed_fields → exclude
            "hr": (_field("badge_id"),),
            # id ∩ allowed → keep
            "ghost": (_field("id"),),
        },
    )

    envelope = use_case.execute(caller=_caller(), call_id=_CALL_ID)

    assert envelope.success is True
    assert envelope.error is None
    assert envelope.data is not None
    assert envelope.meta.trace_id == _TRACE_ID
    assert envelope.meta.operation == _OPERATION

    data = envelope.data
    assert data.count == len(data.datasets) == 2
    by_id = {item.dataset_id: item for item in data.datasets}
    assert set(by_id) == {"sales", "ghost"}
    assert "hr" not in by_id

    sales_summary = by_id["sales"]
    assert isinstance(sales_summary, DatasetSummary)
    assert sales_summary.title == "sales"
    assert sales_summary.description == ""
    assert sales_summary.capabilities == sales.capabilities

    ghost_summary = by_id["ghost"]
    assert ghost_summary.title == "ghost"
    assert ghost_summary.description == ""

    assert policy.calls == [_caller()]
    assert {p.dataset_id for p in catalog.calls} == {"sales", "hr", "ghost"}
    assert len(audit.started) == 1
    assert audit.started[0].status is AuditStatus.STARTED
    assert audit.started[0].call_id == _CALL_ID
    assert len(audit.finished) == 1
    assert audit.finished[0].status is AuditStatus.SUCCEEDED


def test_call_order_started_before_policy_catalog_before_finish() -> None:
    sales = _policy("sales", _PHYSICAL_SALES, ("amount",))
    use_case, log, *_ = _build_use_case(
        policies=frozenset({sales}),
        snapshots={"sales": (_field("amount"),)},
    )

    envelope = use_case.execute(caller=_caller(), call_id=_CALL_ID)
    assert envelope.success is True

    assert "audit.start" in log.events
    assert "policy.list_dataset_policies" in log.events
    assert "catalog.get_field_snapshot:sales" in log.events
    assert "audit.finish" in log.events

    start_i = log.events.index("audit.start")
    policy_i = log.events.index("policy.list_dataset_policies")
    catalog_i = log.events.index("catalog.get_field_snapshot:sales")
    finish_i = log.events.index("audit.finish")
    assert start_i < policy_i < catalog_i < finish_i


def test_empty_policy_returns_succeeded_empty_dataset_list() -> None:
    use_case, log, policy, catalog, audit = _build_use_case(
        policies=frozenset(),
        snapshots={},
    )

    envelope = use_case.execute(caller=_caller(), call_id=_CALL_ID)

    assert envelope.success is True
    assert envelope.error is None
    assert envelope.data is not None
    assert envelope.data.datasets == ()
    assert envelope.data.count == 0
    assert policy.calls == [_caller()]
    assert catalog.calls == []
    assert audit.finished[0].status is AuditStatus.SUCCEEDED


# ---------------------------------------------------------------------------
# Audit gates — STARTED fail rejects; finish fail discards data
# ---------------------------------------------------------------------------


def test_started_audit_failure_rejects_without_policy_or_catalog() -> None:
    sales = _policy("sales", _PHYSICAL_SALES, ("amount",))
    use_case, log, policy, catalog, audit = _build_use_case(
        policies=frozenset({sales}),
        snapshots={"sales": (_field("amount"),)},
        fail_start=True,
    )

    envelope = use_case.execute(caller=_caller(), call_id=_CALL_ID)

    assert envelope.success is False
    assert envelope.data is None
    assert envelope.error is not None
    assert envelope.error.code == ErrorCode.AUDIT_UNAVAILABLE.value
    assert envelope.error.context == {"audit_stage": "start"}
    assert policy.calls == []
    assert catalog.calls == []
    assert "policy.list_dataset_policies" not in log.events
    assert not any(e.startswith("catalog.") for e in log.events)
    assert audit.finished == []


def test_finish_audit_failure_discards_data_returns_audit_unavailable() -> None:
    sales = _policy("sales", _PHYSICAL_SALES, ("amount",))
    use_case, log, policy, catalog, audit = _build_use_case(
        policies=frozenset({sales}),
        snapshots={"sales": (_field("amount"),)},
        fail_finish=True,
    )

    envelope = use_case.execute(caller=_caller(), call_id=_CALL_ID)

    assert envelope.success is False
    assert envelope.data is None
    assert envelope.error is not None
    assert envelope.error.code == ErrorCode.AUDIT_UNAVAILABLE.value
    assert envelope.error.context == {"audit_stage": "finish"}
    # Discovery ran, but terminal audit failure must not leak the list.
    assert policy.calls == [_caller()]
    assert len(catalog.calls) == 1
    assert len(audit.started) == 1
    assert len(audit.finished) == 1


# ---------------------------------------------------------------------------
# Isolation + error taxonomy guards
# ---------------------------------------------------------------------------


def test_summaries_and_envelope_never_expose_physical_table_names() -> None:
    sales = _policy("sales", _PHYSICAL_SALES, ("amount",))
    use_case, *_ = _build_use_case(
        policies=frozenset({sales}),
        snapshots={"sales": (_field("amount"),)},
    )

    envelope = use_case.execute(caller=_caller(), call_id=_CALL_ID)
    assert envelope.success is True
    assert envelope.data is not None

    for summary in envelope.data.datasets:
        assert not hasattr(summary, "physical_table")
        assert _PHYSICAL_SALES not in repr(summary)
        assert _PHYSICAL_SALES not in str(summary)

    blob = repr(envelope.data) + str(envelope.data)
    assert _PHYSICAL_SALES not in blob


def test_list_path_never_emits_dataset_not_allowed() -> None:
    """Empty / partial / audit-fail list paths must not use DATASET_NOT_ALLOWED."""
    sales = _policy("sales", _PHYSICAL_SALES, ("amount",))
    hr = _policy("hr", _PHYSICAL_HR, ("salary",))

    cases = [
        _build_use_case(policies=frozenset(), snapshots={}),
        _build_use_case(
            policies=frozenset({sales, hr}),
            snapshots={
                "sales": (_field("amount"),),
                "hr": (_field("other"),),  # empty intersection → drop, not NOT_ALLOWED
            },
        ),
        _build_use_case(
            policies=frozenset({sales}),
            snapshots={"sales": (_field("amount"),)},
            fail_start=True,
        ),
        _build_use_case(
            policies=frozenset({sales}),
            snapshots={"sales": (_field("amount"),)},
            fail_finish=True,
        ),
    ]

    forbidden = ErrorCode.DATASET_NOT_ALLOWED.value
    for use_case, *_rest in cases:
        envelope = use_case.execute(caller=_caller(), call_id=_CALL_ID)
        if envelope.error is not None:
            assert envelope.error.code != forbidden
        if envelope.data is not None:
            assert forbidden not in repr(envelope.data)


def test_dataset_list_shape_exposes_datasets_and_count() -> None:
    DatasetList, ListAuthorizedDatasets = _load_use_case()
    assert hasattr(DatasetList, "__dataclass_fields__") or hasattr(
        DatasetList, "_fields"
    )
    field_names = set(getattr(DatasetList, "__dataclass_fields__", {}))
    if not field_names and hasattr(DatasetList, "_fields"):
        field_names = set(DatasetList._fields)
    assert field_names == {"datasets", "count"}

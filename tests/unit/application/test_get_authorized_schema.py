"""RED: GetAuthorizedSchema use case (SPEC §9.2 / Step 3.3).

Fake ports only. No production schema symbols until GREEN.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from enterprise_data_mcp.domain.errors import (
    AuditStatus,
    ErrorCode,
    FilterOperator,
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
_CALL_ID = "call-schema-0001"
_TRACE_ID = "trace-schema-aaaa-bbbb-cccc-dddd"
_TIMESTAMP_UTC = "2026-09-13T12:00:00Z"
_OPERATION = "get_authorized_schema"
_CALLER_ID = "demo-stdio-client"
_POLICY_PROFILE = "demo_readonly"

_PHYSICAL_SALES = "phys_sales_secret"
_PHYSICAL_HR = "phys_hr_secret"
_CONN_LEAK = "mysql://user:pass@db.internal:3306/prod"
_SAMPLE_LEAK = "ssn-998-77-6655"

_ALL_FILTER_OPS = frozenset(op.value for op in FilterOperator)


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
    """Import production symbols under test (must fail until 3.3-GREEN)."""
    from enterprise_data_mcp.application.catalog_service import (
        DatasetSchema,
        GetAuthorizedSchema,
    )

    return DatasetSchema, GetAuthorizedSchema


def _build_use_case(
    *,
    policies: frozenset[DatasetPolicy],
    snapshots: dict[str, tuple[FieldSummary, ...]],
    fail_start: bool = False,
    fail_finish: bool = False,
) -> tuple[Any, CallLog, FakePolicyPort, FakeCatalogPort, FakeAuditPort]:
    DatasetSchema, GetAuthorizedSchema = _load_use_case()
    log = CallLog()
    policy = FakePolicyPort(log=log, policies=policies)
    catalog = FakeCatalogPort(log=log, snapshots=snapshots)
    audit = FakeAuditPort(log=log, fail_start=fail_start, fail_finish=fail_finish)
    telemetry = FakeTelemetryPort(log=log)
    clock = FakeClockPort()
    ids = FakeIdPort()
    use_case = GetAuthorizedSchema(
        policy=policy,
        catalog=catalog,
        audit=audit,
        telemetry=telemetry,
        clock=clock,
        ids=ids,
    )
    return use_case, log, policy, catalog, audit


# ---------------------------------------------------------------------------
# Happy path — authorized field intersection + schema shape
# ---------------------------------------------------------------------------


def test_happy_path_returns_field_intersection_schema() -> None:
    sales = _policy("sales", _PHYSICAL_SALES, ("amount", "region"))

    use_case, log, policy, catalog, audit = _build_use_case(
        policies=frozenset({sales}),
        snapshots={
            # amount ∩ allowed → keep; leak_col not in policy → drop
            "sales": (_field("amount"), _field("leak_col"), _field("region")),
        },
    )

    envelope = use_case.execute(
        caller=_caller(), call_id=_CALL_ID, dataset_id="sales"
    )

    assert envelope.success is True
    assert envelope.error is None
    assert envelope.data is not None
    assert envelope.meta.trace_id == _TRACE_ID
    assert envelope.meta.operation == _OPERATION

    data = envelope.data
    assert data.default_limit == 50
    assert data.max_limit == 100
    assert frozenset(data.allowed_filter_operators) == _ALL_FILTER_OPS

    dataset = data.dataset
    assert isinstance(dataset, DatasetSummary)
    assert dataset.dataset_id == "sales"
    assert dataset.title == "sales"
    assert dataset.description == ""
    assert dataset.capabilities == sales.capabilities

    field_ids = [f.field_id for f in data.fields]
    assert field_ids == ["amount", "region"]
    assert "leak_col" not in field_ids
    for item in data.fields:
        assert isinstance(item, FieldSummary)

    assert policy.calls == [_caller()]
    assert [p.dataset_id for p in catalog.calls] == ["sales"]
    assert len(audit.started) == 1
    assert audit.started[0].status is AuditStatus.STARTED
    assert audit.started[0].call_id == _CALL_ID
    assert audit.started[0].dataset == "sales"
    assert len(audit.finished) == 1
    assert audit.finished[0].status is AuditStatus.SUCCEEDED


def test_call_order_started_before_policy_catalog_before_finish() -> None:
    sales = _policy("sales", _PHYSICAL_SALES, ("amount",))
    use_case, log, *_ = _build_use_case(
        policies=frozenset({sales}),
        snapshots={"sales": (_field("amount"),)},
    )

    envelope = use_case.execute(
        caller=_caller(), call_id=_CALL_ID, dataset_id="sales"
    )
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


# ---------------------------------------------------------------------------
# Same-code denial — unauthorized ≡ nonexistent (no enumeration)
# ---------------------------------------------------------------------------


def test_unauthorized_dataset_returns_dataset_not_allowed() -> None:
    sales = _policy("sales", _PHYSICAL_SALES, ("amount",))
    hr = _policy("hr", _PHYSICAL_HR, ("salary",))

    use_case, log, policy, catalog, audit = _build_use_case(
        policies=frozenset({sales}),
        snapshots={"sales": (_field("amount"),)},
    )

    envelope = use_case.execute(
        caller=_caller(), call_id=_CALL_ID, dataset_id="hr"
    )

    assert envelope.success is False
    assert envelope.data is None
    assert envelope.error is not None
    assert envelope.error.code == ErrorCode.DATASET_NOT_ALLOWED.value
    assert envelope.error.context == {"dataset_id": "hr"}
    assert policy.calls == [_caller()]
    assert catalog.calls == []
    assert "catalog.get_field_snapshot" not in "".join(log.events)
    assert len(audit.finished) == 1
    assert audit.finished[0].status is AuditStatus.REJECTED
    assert audit.finished[0].error_code == ErrorCode.DATASET_NOT_ALLOWED.value
    # hr exists only as a decoy policy object elsewhere — must not leak via catalog
    del hr


def test_nonexistent_dataset_returns_same_dataset_not_allowed_code() -> None:
    sales = _policy("sales", _PHYSICAL_SALES, ("amount",))
    use_case, _, policy, catalog, audit = _build_use_case(
        policies=frozenset({sales}),
        snapshots={"sales": (_field("amount"),)},
    )

    envelope = use_case.execute(
        caller=_caller(), call_id=_CALL_ID, dataset_id="does_not_exist"
    )

    assert envelope.success is False
    assert envelope.data is None
    assert envelope.error is not None
    assert envelope.error.code == ErrorCode.DATASET_NOT_ALLOWED.value
    assert envelope.error.context == {"dataset_id": "does_not_exist"}
    assert policy.calls == [_caller()]
    assert catalog.calls == []
    assert audit.finished[0].status is AuditStatus.REJECTED


def test_unauthorized_and_nonexistent_share_identical_error_shape() -> None:
    """Error differences must not enable object enumeration."""
    sales = _policy("sales", _PHYSICAL_SALES, ("amount",))
    use_case, *_ = _build_use_case(
        policies=frozenset({sales}),
        snapshots={"sales": (_field("amount"),)},
    )

    denied = use_case.execute(
        caller=_caller(), call_id=_CALL_ID, dataset_id="hr"
    )
    missing = use_case.execute(
        caller=_caller(), call_id="call-schema-0002", dataset_id="ghost_table"
    )

    assert denied.error is not None and missing.error is not None
    assert denied.error.code == missing.error.code == ErrorCode.DATASET_NOT_ALLOWED.value
    assert set(denied.error.context.keys()) == set(missing.error.context.keys()) == {
        "dataset_id"
    }


def test_empty_field_intersection_rejects_with_dataset_not_allowed() -> None:
    sales = _policy("sales", _PHYSICAL_SALES, ("amount", "region"))
    use_case, _, policy, catalog, audit = _build_use_case(
        policies=frozenset({sales}),
        snapshots={"sales": (_field("leak_col"), _field("other"))},
    )

    envelope = use_case.execute(
        caller=_caller(), call_id=_CALL_ID, dataset_id="sales"
    )

    assert envelope.success is False
    assert envelope.data is None
    assert envelope.error is not None
    assert envelope.error.code == ErrorCode.DATASET_NOT_ALLOWED.value
    assert envelope.error.context == {"dataset_id": "sales"}
    assert policy.calls == [_caller()]
    assert [p.dataset_id for p in catalog.calls] == ["sales"]
    assert audit.finished[0].status is AuditStatus.REJECTED


# ---------------------------------------------------------------------------
# Audit gates — STARTED fail rejects; finish fail discards schema
# ---------------------------------------------------------------------------


def test_started_audit_failure_rejects_without_policy_or_catalog() -> None:
    sales = _policy("sales", _PHYSICAL_SALES, ("amount",))
    use_case, log, policy, catalog, audit = _build_use_case(
        policies=frozenset({sales}),
        snapshots={"sales": (_field("amount"),)},
        fail_start=True,
    )

    envelope = use_case.execute(
        caller=_caller(), call_id=_CALL_ID, dataset_id="sales"
    )

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


def test_finish_audit_failure_discards_schema_returns_audit_unavailable() -> None:
    sales = _policy("sales", _PHYSICAL_SALES, ("amount",))
    use_case, log, policy, catalog, audit = _build_use_case(
        policies=frozenset({sales}),
        snapshots={"sales": (_field("amount"),)},
        fail_finish=True,
    )

    envelope = use_case.execute(
        caller=_caller(), call_id=_CALL_ID, dataset_id="sales"
    )

    assert envelope.success is False
    assert envelope.data is None
    assert envelope.error is not None
    assert envelope.error.code == ErrorCode.AUDIT_UNAVAILABLE.value
    assert envelope.error.context == {"audit_stage": "finish"}
    assert policy.calls == [_caller()]
    assert len(catalog.calls) == 1
    assert len(audit.started) == 1
    assert len(audit.finished) == 1


# ---------------------------------------------------------------------------
# Isolation — no physical table / connection / sensitive samples
# ---------------------------------------------------------------------------


def test_schema_never_exposes_physical_table_connection_or_samples() -> None:
    sales = _policy("sales", _PHYSICAL_SALES, ("amount",))
    use_case, *_ = _build_use_case(
        policies=frozenset({sales}),
        snapshots={"sales": (_field("amount"),)},
    )

    envelope = use_case.execute(
        caller=_caller(), call_id=_CALL_ID, dataset_id="sales"
    )
    assert envelope.success is True
    assert envelope.data is not None

    data = envelope.data
    assert not hasattr(data, "physical_table")
    assert not hasattr(data.dataset, "physical_table")
    for item in data.fields:
        assert not hasattr(item, "sample")
        assert not hasattr(item, "example")
        assert not hasattr(item, "physical_column")

    blob = repr(data) + str(data) + repr(envelope)
    assert _PHYSICAL_SALES not in blob
    assert _CONN_LEAK not in blob
    assert _SAMPLE_LEAK not in blob


def test_dataset_schema_shape_exposes_required_fields() -> None:
    DatasetSchema, GetAuthorizedSchema = _load_use_case()
    assert hasattr(DatasetSchema, "__dataclass_fields__") or hasattr(
        DatasetSchema, "_fields"
    )
    field_names = set(getattr(DatasetSchema, "__dataclass_fields__", {}))
    if not field_names and hasattr(DatasetSchema, "_fields"):
        field_names = set(DatasetSchema._fields)
    assert field_names == {
        "dataset",
        "fields",
        "default_limit",
        "max_limit",
        "allowed_filter_operators",
    }

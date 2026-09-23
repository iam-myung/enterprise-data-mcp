"""RED: MCP Resource template …/datasets/{dataset_id}/schema (API §5.2 / Step 9.2).

No production schema_resource until 9.2-GREEN.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from enterprise_data_mcp.domain.errors import ErrorCode, TransportKind
from enterprise_data_mcp.domain.models import (
    AuditRecord,
    CallerContext,
    Capability,
    DatasetPolicy,
    FieldSummary,
    ValueType,
)

_SCHEMA_URI_TEMPLATE = "enterprise-data://datasets/{dataset_id}/schema"
_CALL_ID = "call-mcp-schema-0001"
_TRACE_ID = "trace-mcp-schema-aaaa-bbbb"
_TIMESTAMP_UTC = "2026-09-14T00:00:00Z"
_OPERATION = "get_authorized_schema"
_CALLER_ID = "demo-stdio-client"
_POLICY_PROFILE = "demo_readonly"
_PHYSICAL_SALES = "phys_sales_secret"
_PHYSICAL_HR = "phys_hr_secret"


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
        self.log.add("telemetry.start_span")

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
        self.log.add("policy.list")
        return self.policies


@dataclass
class FakeCatalogPort:
    log: CallLog
    snapshots: Mapping[str, tuple[FieldSummary, ...]]

    def get_field_snapshot(
        self, policy: DatasetPolicy
    ) -> tuple[FieldSummary, ...]:
        self.log.add("catalog.get")
        return self.snapshots[policy.dataset_id]


def _caller() -> CallerContext:
    return CallerContext(
        caller_id=_CALLER_ID,
        policy_profile=_POLICY_PROFILE,
        transport=TransportKind.STDIO,
    )


def _field(field_id: str) -> FieldSummary:
    return FieldSummary(
        field_id=field_id,
        title=field_id,
        value_type=ValueType.STRING,
        nullable=True,
        filterable=True,
        aggregatable=False,
        sortable=True,
    )


def _policy(
    dataset_id: str, physical: str, fields: tuple[str, ...]
) -> DatasetPolicy:
    return DatasetPolicy(
        dataset_id=dataset_id,
        physical_table=physical,
        allowed_fields=fields,
        capabilities=(Capability.READ_DETAIL, Capability.FILTER),
    )


def _build_use_case(
    *,
    policies: frozenset[DatasetPolicy],
    snapshots: Mapping[str, tuple[FieldSummary, ...]],
) -> Any:
    from enterprise_data_mcp.application.catalog_service import (
        GetAuthorizedSchema,
    )

    log = CallLog()
    return GetAuthorizedSchema(
        policy=FakePolicyPort(log=log, policies=policies),
        catalog=FakeCatalogPort(log=log, snapshots=snapshots),
        audit=FakeAuditPort(log=log),
        telemetry=FakeTelemetryPort(log=log),
        clock=FakeClockPort(),
        ids=FakeIdPort(),
    )


def _schema_uri_template() -> str:
    from enterprise_data_mcp.adapters.inbound.mcp.uri_constants import (
        SCHEMA_URI_TEMPLATE,
    )

    return SCHEMA_URI_TEMPLATE


def _codec() -> Any:
    from enterprise_data_mcp.adapters.inbound.mcp.envelope_codec import (
        envelope_to_jsonable,
    )

    return envelope_to_jsonable


def _read_schema_payload(
    *, use_case: Any, dataset_id: str, call_id: str = _CALL_ID
) -> dict[str, Any]:
    from enterprise_data_mcp.adapters.inbound.mcp.schema_resource import (
        read_schema_resource,
    )

    return read_schema_resource(
        use_case=use_case,
        caller=_caller(),
        call_id=call_id,
        dataset_id=dataset_id,
    )


def _assert_envelope_invariants(payload: Mapping[str, Any]) -> None:
    assert "success" in payload
    assert "data" in payload
    assert "error" in payload
    assert "meta" in payload
    meta = payload["meta"]
    assert set(meta) >= {"trace_id", "timestamp_utc", "operation", "duration_ms"}
    if payload["success"] is True:
        assert payload["data"] is not None
        assert payload["error"] is None
    else:
        assert payload["data"] is None
        assert payload["error"] is not None
        assert "code" in payload["error"]
        assert "message" in payload["error"]
        assert "context" in payload["error"]


def test_schema_uri_template_matches_api_5_2() -> None:
    assert _schema_uri_template() == _SCHEMA_URI_TEMPLATE


def test_envelope_codec_serializes_success_dataset_schema_shape() -> None:
    sales = _policy("sales", _PHYSICAL_SALES, ("amount", "region"))
    use_case = _build_use_case(
        policies=frozenset({sales}),
        snapshots={"sales": (_field("amount"), _field("region"), _field("leak"))},
    )
    envelope = use_case.execute(
        caller=_caller(), call_id=_CALL_ID, dataset_id="sales"
    )
    assert envelope.success is True

    payload = _codec()(envelope)
    _assert_envelope_invariants(payload)
    assert payload["success"] is True
    data = payload["data"]
    assert data["dataset"]["dataset_id"] == "sales"
    assert {f["field_id"] for f in data["fields"]} == {"amount", "region"}
    assert data["default_limit"] == 50
    assert data["max_limit"] == 100
    assert isinstance(data["allowed_filter_operators"], list)
    assert payload["meta"]["operation"] == _OPERATION
    json.dumps(payload)


def test_read_schema_resource_returns_success_envelope_vector() -> None:
    sales = _policy("sales", _PHYSICAL_SALES, ("amount",))
    use_case = _build_use_case(
        policies=frozenset({sales}),
        snapshots={"sales": (_field("amount"),)},
    )
    payload = _read_schema_payload(use_case=use_case, dataset_id="sales")
    _assert_envelope_invariants(payload)
    assert payload["success"] is True
    assert payload["error"] is None
    assert payload["data"]["dataset"]["dataset_id"] == "sales"
    assert payload["data"]["fields"][0]["field_id"] == "amount"
    assert "value_type" in payload["data"]["fields"][0]
    assert payload["meta"]["operation"] == _OPERATION


def test_unauthorized_and_missing_dataset_share_dataset_not_allowed_code() -> None:
    """API §5.2: unauthorized ≡ missing — same ErrorCode, no enumeration."""
    sales = _policy("sales", _PHYSICAL_SALES, ("amount",))
    use_case = _build_use_case(
        policies=frozenset({sales}),
        snapshots={"sales": (_field("amount"),)},
    )
    denied = _read_schema_payload(use_case=use_case, dataset_id="hr")
    missing = _read_schema_payload(use_case=use_case, dataset_id="does_not_exist")

    _assert_envelope_invariants(denied)
    _assert_envelope_invariants(missing)
    assert denied["success"] is False
    assert missing["success"] is False
    assert denied["error"]["code"] == ErrorCode.DATASET_NOT_ALLOWED.value
    assert missing["error"]["code"] == ErrorCode.DATASET_NOT_ALLOWED.value
    # Same code; context carries requested id only (no privilege oracle).
    assert denied["error"]["context"] == {"dataset_id": "hr"}
    assert missing["error"]["context"] == {"dataset_id": "does_not_exist"}
    blob = json.dumps(denied) + json.dumps(missing)
    assert _PHYSICAL_HR not in blob
    assert _PHYSICAL_SALES not in blob


def test_read_schema_resource_never_exposes_physical_table() -> None:
    sales = _policy("sales", _PHYSICAL_SALES, ("amount",))
    use_case = _build_use_case(
        policies=frozenset({sales}),
        snapshots={"sales": (_field("amount"),)},
    )
    payload = _read_schema_payload(use_case=use_case, dataset_id="sales")
    blob = json.dumps(payload)
    assert _PHYSICAL_SALES not in blob
    assert "physical_table" not in blob
    assert "phys_" not in blob

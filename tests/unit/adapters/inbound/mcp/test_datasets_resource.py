"""RED: MCP Resource enterprise-data://datasets — Envelope contract (API §5.1 / Step 9.1).

No production inbound MCP adapter until 9.1-GREEN.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from enterprise_data_mcp.domain.errors import (
    ErrorCode,
    TransportKind,
)
from enterprise_data_mcp.domain.models import (
    AuditRecord,
    CallerContext,
    Capability,
    DatasetPolicy,
    FieldSummary,
    ValueType,
)

_DATASETS_URI = "enterprise-data://datasets"
_CALL_ID = "call-mcp-datasets-0001"
_TRACE_ID = "trace-mcp-datasets-aaaa-bbbb"
_TIMESTAMP_UTC = "2026-09-14T00:00:00Z"
_OPERATION = "list_authorized_datasets"
_CALLER_ID = "demo-stdio-client"
_POLICY_PROFILE = "demo_readonly"
_PHYSICAL_SALES = "phys_sales_secret"


# ---------------------------------------------------------------------------
# Deterministic fake ports (resource adapter tests only)
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
    fail_start: bool = False,
    fail_finish: bool = False,
) -> Any:
    from enterprise_data_mcp.application.catalog_service import (
        ListAuthorizedDatasets,
    )

    log = CallLog()
    return ListAuthorizedDatasets(
        policy=FakePolicyPort(log=log, policies=policies),
        catalog=FakeCatalogPort(log=log, snapshots=snapshots),
        audit=FakeAuditPort(
            log=log, fail_start=fail_start, fail_finish=fail_finish
        ),
        telemetry=FakeTelemetryPort(log=log),
        clock=FakeClockPort(),
        ids=FakeIdPort(),
    )


def _uri_constant() -> str:
    from enterprise_data_mcp.adapters.inbound.mcp.uri_constants import (
        DATASETS_URI,
    )

    return DATASETS_URI


def _codec() -> Any:
    from enterprise_data_mcp.adapters.inbound.mcp.envelope_codec import (
        envelope_to_jsonable,
    )

    return envelope_to_jsonable


def _read_datasets_payload(*, use_case: Any, call_id: str = _CALL_ID) -> dict[str, Any]:
    """Sync Resource read surface used by unit contract vectors."""
    from enterprise_data_mcp.adapters.inbound.mcp.datasets_resource import (
        read_datasets_resource,
    )

    return read_datasets_resource(
        use_case=use_case, caller=_caller(), call_id=call_id
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


# ---------------------------------------------------------------------------
# Contract vectors
# ---------------------------------------------------------------------------


def test_datasets_uri_constant_matches_api_5_1() -> None:
    assert _uri_constant() == _DATASETS_URI


def test_envelope_codec_round_trips_success_dataset_list_shape() -> None:
    sales = _policy("sales", _PHYSICAL_SALES, ("amount",))
    use_case = _build_use_case(
        policies=frozenset({sales}),
        snapshots={"sales": (_field("amount"),)},
    )
    envelope = use_case.execute(caller=_caller(), call_id=_CALL_ID)
    assert envelope.success is True

    codec = _codec()
    payload = codec(envelope)
    _assert_envelope_invariants(payload)
    assert payload["success"] is True
    assert payload["data"]["count"] == 1
    assert payload["data"]["datasets"][0]["dataset_id"] == "sales"
    assert payload["meta"]["operation"] == _OPERATION
    assert payload["meta"]["trace_id"] == _TRACE_ID
    # JSON-serializable (MCP Resource content).
    json.dumps(payload)


def test_read_datasets_resource_returns_success_envelope_vector() -> None:
    sales = _policy("sales", _PHYSICAL_SALES, ("amount", "region"))
    use_case = _build_use_case(
        policies=frozenset({sales}),
        snapshots={"sales": (_field("amount"), _field("region"))},
    )
    payload = _read_datasets_payload(use_case=use_case)
    _assert_envelope_invariants(payload)
    assert payload["success"] is True
    assert payload["error"] is None
    data = payload["data"]
    assert data["count"] == len(data["datasets"]) == 1
    assert data["datasets"][0]["dataset_id"] == "sales"
    assert "title" in data["datasets"][0]
    assert "description" in data["datasets"][0]
    assert "capabilities" in data["datasets"][0]
    assert payload["meta"]["operation"] == _OPERATION


def test_read_datasets_resource_audit_start_failure_is_audit_unavailable() -> None:
    sales = _policy("sales", _PHYSICAL_SALES, ("amount",))
    use_case = _build_use_case(
        policies=frozenset({sales}),
        snapshots={"sales": (_field("amount"),)},
        fail_start=True,
    )
    payload = _read_datasets_payload(use_case=use_case)
    _assert_envelope_invariants(payload)
    assert payload["success"] is False
    assert payload["data"] is None
    assert payload["error"]["code"] == ErrorCode.AUDIT_UNAVAILABLE.value
    assert payload["error"]["context"] == {"audit_stage": "start"}


def test_read_datasets_resource_never_exposes_physical_table() -> None:
    sales = _policy("sales", _PHYSICAL_SALES, ("amount",))
    use_case = _build_use_case(
        policies=frozenset({sales}),
        snapshots={"sales": (_field("amount"),)},
    )
    payload = _read_datasets_payload(use_case=use_case)
    blob = json.dumps(payload)
    assert _PHYSICAL_SALES not in blob
    assert "physical_table" not in blob
    assert "phys_" not in blob

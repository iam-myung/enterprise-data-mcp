"""RED: MCP Tool query_data — dual-channel Envelope (API §6–§7 / Step 9.3).

No production query_data_tool until 9.3-GREEN.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from enterprise_data_mcp.domain.errors import (
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

_TOOL_NAME = "query_data"
_CALL_ID = "call-mcp-query-0001"
_TRACE_ID = "trace-mcp-query-aaaa"
_TIMESTAMP_UTC = "2026-09-14T00:00:00Z"
_CALLER_ID = "demo-stdio-client"
_POLICY_PROFILE = "demo_readonly"
_DATASET = "sales_inventory_daily"
_PHYSICAL = "v_sales_inventory_daily"


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
        return None

    def record_event(
        self, trace_id: str, event: str, fields: Mapping[str, object]
    ) -> None:
        return None

    def record_metric(
        self, name: str, value: float, labels: Mapping[str, object]
    ) -> None:
        return None


@dataclass
class FakeAuditPort:
    log: CallLog

    def start(self, record: AuditRecord) -> None:
        return None

    def finish(self, record: AuditRecord) -> None:
        return None


@dataclass
class FakePolicyPort:
    log: CallLog
    policies: frozenset[DatasetPolicy]

    def list_dataset_policies(self, caller: CallerContext) -> frozenset[DatasetPolicy]:
        return self.policies


@dataclass
class FakeCatalogPort:
    log: CallLog
    snapshots: Mapping[str, tuple[FieldSummary, ...]]

    def get_field_snapshot(
        self, authorized: DatasetPolicy
    ) -> tuple[FieldSummary, ...]:
        return self.snapshots[authorized.dataset_id]


@dataclass
class FakeQueryPort:
    log: CallLog
    result: QueryResult

    def execute(self, plan: QueryPlan) -> tuple[QueryResult, int]:
        return self.result, 1


def _caller() -> CallerContext:
    return CallerContext(
        caller_id=_CALLER_ID,
        policy_profile=_POLICY_PROFILE,
        transport=TransportKind.STDIO,
    )


def _field(field_id: str, value_type: ValueType = ValueType.STRING) -> FieldSummary:
    return FieldSummary(
        field_id=field_id,
        title=field_id,
        value_type=value_type,
        nullable=True,
        filterable=True,
        aggregatable=True,
        sortable=True,
    )


def _policy() -> DatasetPolicy:
    return DatasetPolicy(
        dataset_id=_DATASET,
        physical_table=_PHYSICAL,
        allowed_fields=("product_name", "quantity"),
        capabilities=(Capability.READ_DETAIL, Capability.FILTER),
    )


def _empty_result() -> QueryResult:
    return QueryResult(
        result_status=ResultStatus.EMPTY,
        columns=("product_name", "quantity"),
        rows=(),
        row_count=0,
        truncated=False,
        source=QueryResultSource(
            dataset_id=_DATASET, queried_at_utc=_TIMESTAMP_UTC
        ),
    )


def _detail_request(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "dataset_id": _DATASET,
        "projection": ["product_name", "quantity"],
        "filters": [],
        "aggregations": [],
        "group_by": [],
        "order_by": [],
        "limit": 10,
    }
    base.update(overrides)
    return base


def _build_use_case(*, result: QueryResult | None = None) -> Any:
    from enterprise_data_mcp.application.query_service import ExecuteReadQuery

    log = CallLog()
    policy = _policy()
    return ExecuteReadQuery(
        policy=FakePolicyPort(log=log, policies=frozenset({policy})),
        catalog=FakeCatalogPort(
            log=log,
            snapshots={
                _DATASET: (
                    _field("product_name"),
                    _field("quantity", ValueType.INTEGER),
                )
            },
        ),
        query=FakeQueryPort(log=log, result=result or _empty_result()),
        audit=FakeAuditPort(log=log),
        telemetry=FakeTelemetryPort(log=log),
        clock=FakeClockPort(),
        ids=FakeIdPort(),
    )


def _invoke_query_data(request: Mapping[str, object]) -> dict[str, Any]:
    from enterprise_data_mcp.adapters.inbound.mcp.query_data_tool import (
        invoke_query_data,
    )

    return invoke_query_data(
        use_case=_build_use_case(),
        caller=_caller(),
        call_id=_CALL_ID,
        request=dict(request),
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


def test_query_data_tool_name_constant() -> None:
    from enterprise_data_mcp.adapters.inbound.mcp.query_data_tool import (
        QUERY_DATA_TOOL_NAME,
    )

    assert QUERY_DATA_TOOL_NAME == _TOOL_NAME


def test_envelope_codec_serializes_empty_query_result_as_success() -> None:
    from enterprise_data_mcp.adapters.inbound.mcp.envelope_codec import (
        envelope_to_jsonable,
    )

    use_case = _build_use_case(result=_empty_result())
    envelope = use_case.execute(
        caller=_caller(), call_id=_CALL_ID, request=_detail_request()
    )
    assert envelope.success is True
    payload = envelope_to_jsonable(envelope)
    _assert_envelope_invariants(payload)
    assert payload["success"] is True
    assert payload["data"]["result_status"] == ResultStatus.EMPTY.value
    assert payload["data"]["row_count"] == 0
    assert payload["meta"]["operation"] == _TOOL_NAME
    json.dumps(payload)


def test_invoke_query_data_empty_is_success_not_error() -> None:
    payload = _invoke_query_data(_detail_request())
    _assert_envelope_invariants(payload)
    assert payload["success"] is True
    assert payload["error"] is None
    assert payload["data"]["result_status"] == "EMPTY"


def test_invoke_query_data_rejects_raw_sql_as_write_forbidden() -> None:
    payload = _invoke_query_data(_detail_request(raw_sql="SELECT 1"))
    _assert_envelope_invariants(payload)
    assert payload["success"] is False
    assert payload["error"]["code"] == ErrorCode.WRITE_OPERATION_FORBIDDEN.value
    blob = json.dumps(payload)
    assert "SELECT 1" not in blob
    assert _PHYSICAL not in blob


def test_invoke_query_data_unknown_field_is_validation_error() -> None:
    payload = _invoke_query_data(_detail_request(unexpected_field="x"))
    _assert_envelope_invariants(payload)
    assert payload["success"] is False
    assert payload["error"]["code"] == ErrorCode.VALIDATION_ERROR.value


def test_invoke_query_data_never_exposes_physical_table() -> None:
    payload = _invoke_query_data(_detail_request())
    blob = json.dumps(payload)
    assert _PHYSICAL not in blob
    assert "physical_table" not in blob

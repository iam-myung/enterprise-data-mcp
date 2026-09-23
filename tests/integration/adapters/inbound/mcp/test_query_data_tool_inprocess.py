"""RED: in-process FastMCP query_data dual-channel Envelope (API §6–§7 / Step 9.3).

No production query_data_tool until 9.3-GREEN. No Host process.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from enterprise_data_mcp.domain.errors import ResultStatus, TransportKind
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
_CALL_ID = "call-mcp-query-smoke-0001"
_TRACE_ID = "trace-mcp-query-smoke"
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


def _build_use_case() -> Any:
    from enterprise_data_mcp.application.query_service import ExecuteReadQuery

    log = CallLog()
    policy = DatasetPolicy(
        dataset_id=_DATASET,
        physical_table=_PHYSICAL,
        allowed_fields=("product_name", "quantity"),
        capabilities=(Capability.READ_DETAIL, Capability.FILTER),
    )
    fields = (
        FieldSummary(
            field_id="product_name",
            title="product_name",
            value_type=ValueType.STRING,
            nullable=False,
            filterable=True,
            aggregatable=False,
            sortable=True,
        ),
        FieldSummary(
            field_id="quantity",
            title="quantity",
            value_type=ValueType.INTEGER,
            nullable=False,
            filterable=True,
            aggregatable=True,
            sortable=True,
        ),
    )
    empty = QueryResult(
        result_status=ResultStatus.EMPTY,
        columns=("product_name", "quantity"),
        rows=(),
        row_count=0,
        truncated=False,
        source=QueryResultSource(
            dataset_id=_DATASET, queried_at_utc=_TIMESTAMP_UTC
        ),
    )
    return ExecuteReadQuery(
        policy=FakePolicyPort(log=log, policies=frozenset({policy})),
        catalog=FakeCatalogPort(log=log, snapshots={_DATASET: fields}),
        query=FakeQueryPort(log=log, result=empty),
        audit=FakeAuditPort(log=log),
        telemetry=FakeTelemetryPort(log=log),
        clock=FakeClockPort(),
        ids=FakeIdPort(),
    )


def _build_mcp() -> Any:
    from enterprise_data_mcp.adapters.inbound.mcp.query_data_tool import (
        build_query_data_mcp,
    )

    return build_query_data_mcp(
        use_case=_build_use_case(),
        caller=_caller(),
        call_id=_CALL_ID,
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


def test_inprocess_query_data_dual_channel_and_write_reject() -> None:
    mcp = _build_mcp()

    async def _run() -> None:
        tools = await mcp.list_tools()
        names = {t.name for t in tools}
        assert _TOOL_NAME in names
        assert "raw_sql" not in names
        assert "execute_sql" not in names

        result = await mcp.call_tool(
            _TOOL_NAME, {"request": _detail_request()}
        )
        assert result.structured_content is not None
        structured = dict(result.structured_content)
        assert result.content, "expected text channel"
        text_payload = json.loads(result.content[0].text)
        # Dual-channel: same Envelope semantics.
        assert structured["success"] is True
        assert text_payload["success"] is True
        assert structured["data"]["result_status"] == "EMPTY"
        assert text_payload["data"]["result_status"] == "EMPTY"
        assert structured["meta"]["operation"] == _TOOL_NAME
        assert text_payload["meta"]["operation"] == _TOOL_NAME
        assert structured["error"] is None
        assert text_payload["error"] is None
        assert _PHYSICAL not in result.content[0].text

        denied = await mcp.call_tool(
            _TOOL_NAME,
            {"request": _detail_request(raw_sql="SELECT * FROM secret")},
        )
        denied_structured = dict(denied.structured_content or {})
        denied_text = json.loads(denied.content[0].text)
        assert denied_structured["success"] is False
        assert denied_text["success"] is False
        assert denied_structured["error"]["code"] == "WRITE_OPERATION_FORBIDDEN"
        assert denied_text["error"]["code"] == "WRITE_OPERATION_FORBIDDEN"
        assert "SELECT * FROM secret" not in denied.content[0].text

    asyncio.run(_run())

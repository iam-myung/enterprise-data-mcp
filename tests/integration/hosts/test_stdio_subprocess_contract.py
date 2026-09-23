"""RED: stdio Host subprocess / in-process contract vectors (SPEC Step 10 / API §2).

No production Host wiring until 10-GREEN. Contract vectors, not manual连调.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import anyio
from fastmcp import Client
from fastmcp.client.transports import StdioTransport

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

PROJECT_ROOT = Path(__file__).resolve().parents[3]

_DATASETS_URI = "enterprise-data://datasets"
_SCHEMA_URI = "enterprise-data://datasets/sales_inventory_daily/schema"
_TOOL_NAME = "query_data"
_CALL_ID = "call-stdio-integ-0001"
_TRACE_ID = "trace-stdio-integ-bbbb"
_TIMESTAMP_UTC = "2026-09-14T00:00:00Z"
_CALLER_ID = "demo-stdio-client"
_POLICY_PROFILE = "demo_readonly"
_DATASET = "sales_inventory_daily"
_PHYSICAL = "phys_sales_secret"
_PRIMARY_PROTOCOL = "2026-07-28"


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


def _use_cases() -> tuple[Any, Any, Any]:
    from enterprise_data_mcp.application.catalog_service import (
        GetAuthorizedSchema,
        ListAuthorizedDatasets,
    )
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
    ports = dict(
        policy=FakePolicyPort(log=log, policies=frozenset({policy})),
        catalog=FakeCatalogPort(log=log, snapshots={_DATASET: fields}),
        audit=FakeAuditPort(log=log),
        telemetry=FakeTelemetryPort(log=log),
        clock=FakeClockPort(),
        ids=FakeIdPort(),
    )
    return (
        ListAuthorizedDatasets(**ports),
        GetAuthorizedSchema(**ports),
        ExecuteReadQuery(
            **ports,
            query=FakeQueryPort(log=log, result=empty),
        ),
    )


def test_inprocess_compose_list_read_call_contract() -> None:
    from enterprise_data_mcp.adapters.inbound.mcp.compose import compose_enterprise_mcp

    list_uc, schema_uc, query_uc = _use_cases()
    mcp = compose_enterprise_mcp(
        list_datasets=list_uc,
        get_schema=schema_uc,
        execute_query=query_uc,
        caller=_caller(),
        call_id=_CALL_ID,
    )

    async def _run() -> None:
        resources = await mcp.list_resources()
        assert _DATASETS_URI in {str(r.uri) for r in resources}

        listed = await mcp.read_resource(_DATASETS_URI)
        listed_raw = listed.contents[0].content
        listed_payload = json.loads(listed_raw)
        assert listed_payload["success"] is True
        assert _PHYSICAL not in listed_raw

        schema = await mcp.read_resource(_SCHEMA_URI)
        schema_payload = json.loads(schema.contents[0].content)
        assert schema_payload["success"] is True
        assert schema_payload["data"]["dataset"]["dataset_id"] == _DATASET

        result = await mcp.call_tool(
            _TOOL_NAME,
            {
                "request": {
                    "dataset_id": _DATASET,
                    "projection": ["product_name"],
                    "filters": [],
                    "aggregations": [],
                    "group_by": [],
                    "order_by": [],
                    "limit": 10,
                }
            },
        )
        # Dual-channel: structured content preferred when present
        if result.structured_content is not None:
            payload = result.structured_content
        else:
            assert result.content, "expected tool text content"
            payload = json.loads(result.content[0].text)
        assert payload["success"] is True
        assert payload["data"]["result_status"] == "EMPTY"
        assert _PHYSICAL not in json.dumps(payload)

        tools = await mcp.list_tools()
        names = {t.name for t in tools}
        assert _TOOL_NAME in names
        assert "execute_sql" not in names

    asyncio.run(_run())


def test_stdio_subprocess_list_read_call_and_protocol() -> None:
    """Real stdio subprocess: handshake + business surface (demo container)."""

    async def _run() -> dict[str, Any]:
        transport = StdioTransport(
            command=sys.executable,
            args=["-m", "enterprise_data_mcp.hosts.stdio"],
            cwd=str(PROJECT_ROOT),
            env={
                **os.environ,
                "MCP_CALLER_ID": _CALLER_ID,
                "MCP_POLICY_PROFILE": _POLICY_PROFILE,
                "MCP_TRANSPORT": "stdio",
                "ENTERPRISE_DATA_MCP_STDIO_DEMO": "1",
            },
        )
        async with Client(transport) as client:
            version = client.protocol_version
            resources = await client.list_resources()
            uris = {str(r.uri) for r in resources}
            listed = await client.read_resource(_DATASETS_URI)
            tools = await client.list_tools()
            names = {t.name for t in tools}
            call = await client.call_tool(
                _TOOL_NAME,
                {
                    "request": {
                        "dataset_id": _DATASET,
                        "projection": ["product_name"],
                        "filters": [],
                        "aggregations": [],
                        "group_by": [],
                        "order_by": [],
                        "limit": 10,
                    }
                },
            )
            return {
                "version": version,
                "uris": uris,
                "listed": listed,
                "names": names,
                "call": call,
            }

    out = anyio.run(_run)
    assert out["version"] == _PRIMARY_PROTOCOL
    assert _DATASETS_URI in out["uris"]
    assert _TOOL_NAME in out["names"]
    assert "execute_sql" not in out["names"]

    listed = out["listed"]
    # Client.read_resource returns list[TextResourceContents]
    listed_raw = listed[0].text if isinstance(listed, list) else listed.contents[0].content
    listed_payload = json.loads(listed_raw)
    assert listed_payload["success"] is True
    assert _PHYSICAL not in listed_raw

    call = out["call"]
    if getattr(call, "structured_content", None) is not None:
        payload = call.structured_content
    else:
        # Client may return CallToolResult with .data or content list
        data = getattr(call, "data", None)
        if isinstance(data, dict):
            payload = data
        else:
            content = getattr(call, "content", None) or []
            payload = json.loads(content[0].text)
    assert payload["success"] is True
    assert payload["data"]["result_status"] == "EMPTY"


def test_stdio_startup_log_must_not_pollute_stdout_probe() -> None:
    """Unit-level Host helper: log JSON goes to stderr stream, not stdout buffer."""
    import io

    from enterprise_data_mcp.hosts.stdio import emit_host_log

    fake_out = io.StringIO()
    fake_err = io.StringIO()
    emit_host_log(
        stream=fake_err,
        level="INFO",
        event="stdio.host.start",
        trace_id=_TRACE_ID,
        operation="stdio_host",
        status="ok",
        duration_ms=0,
        transport="stdio",
    )
    assert fake_out.getvalue() == ""
    err_line = fake_err.getvalue().strip()
    assert '"event": "stdio.host.start"' in err_line or '"event":"stdio.host.start"' in err_line
    assert "stdio.host.start" in err_line

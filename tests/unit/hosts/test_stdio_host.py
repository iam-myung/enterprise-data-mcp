"""RED: stdio Host unit contracts (API §2 / SPEC Step 10).

No production compose / bootstrap / build_stdio_server until 10-GREEN.
"""

from __future__ import annotations

import io
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

_DATASETS_URI = "enterprise-data://datasets"
_SCHEMA_URI = "enterprise-data://datasets/sales_inventory_daily/schema"
_TOOL_NAME = "query_data"
_CALL_ID = "call-stdio-host-0001"
_TRACE_ID = "trace-stdio-host-aaaa"
_TIMESTAMP_UTC = "2026-09-14T00:00:00Z"
_CALLER_ID = "demo-stdio-client"
_POLICY_PROFILE = "demo_readonly"
_DATASET = "sales_inventory_daily"
_PHYSICAL = "phys_sales_secret"


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


def _policy() -> DatasetPolicy:
    return DatasetPolicy(
        dataset_id=_DATASET,
        physical_table=_PHYSICAL,
        allowed_fields=("product_name", "quantity"),
        capabilities=(Capability.READ_DETAIL, Capability.FILTER),
    )


def _fields() -> tuple[FieldSummary, ...]:
    return (
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


def _use_cases() -> tuple[Any, Any, Any]:
    from enterprise_data_mcp.application.catalog_service import (
        GetAuthorizedSchema,
        ListAuthorizedDatasets,
    )
    from enterprise_data_mcp.application.query_service import ExecuteReadQuery

    log = CallLog()
    policy = _policy()
    fields = _fields()
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


def test_compose_enterprise_mcp_module_importable() -> None:
    from enterprise_data_mcp.adapters.inbound.mcp.compose import (  # noqa: F401
        compose_enterprise_mcp,
    )


def test_compose_exposes_datasets_schema_and_query_data() -> None:
    import asyncio

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
        uris = {str(r.uri) for r in resources}
        assert _DATASETS_URI in uris

        templates = await mcp.list_resource_templates()
        template_uris = {str(t.uri_template) for t in templates}
        assert any("datasets/{dataset_id}/schema" in u for u in template_uris)

        tools = await mcp.list_tools()
        names = {t.name for t in tools}
        assert _TOOL_NAME in names
        assert "execute_sql" not in names
        assert "raw_sql" not in names
        assert "run_sql" not in names

    asyncio.run(_run())


def test_load_stdio_settings_binds_caller_and_stdio_transport() -> None:
    from enterprise_data_mcp.bootstrap.settings import load_stdio_settings

    settings = load_stdio_settings(
        {
            "MCP_CALLER_ID": _CALLER_ID,
            "MCP_POLICY_PROFILE": _POLICY_PROFILE,
            "MCP_TRANSPORT": "stdio",
        }
    )
    assert settings.caller_id == _CALLER_ID
    assert settings.policy_profile == _POLICY_PROFILE
    assert settings.transport == TransportKind.STDIO


def test_build_demo_container_and_stdio_server_surface() -> None:
    import asyncio

    from enterprise_data_mcp.bootstrap.container import build_demo_container
    from enterprise_data_mcp.bootstrap.settings import load_stdio_settings
    from enterprise_data_mcp.hosts import build_stdio_server

    settings = load_stdio_settings(
        {
            "MCP_CALLER_ID": _CALLER_ID,
            "MCP_POLICY_PROFILE": _POLICY_PROFILE,
            "MCP_TRANSPORT": "stdio",
        }
    )
    container = build_demo_container(settings)
    mcp = build_stdio_server(container=container)

    async def _run() -> None:
        resources = await mcp.list_resources()
        assert _DATASETS_URI in {str(r.uri) for r in resources}
        tools = await mcp.list_tools()
        assert _TOOL_NAME in {t.name for t in tools}

    asyncio.run(_run())


def test_emit_host_log_writes_json_only_to_given_stream() -> None:
    from enterprise_data_mcp.hosts.stdio import emit_host_log

    stream = io.StringIO()
    emit_host_log(
        stream=stream,
        level="INFO",
        event="stdio.host.start",
        trace_id=_TRACE_ID,
        operation="stdio_host",
        status="ok",
        duration_ms=0,
        transport="stdio",
    )
    line = stream.getvalue().strip()
    payload = json.loads(line)
    assert payload["event"] == "stdio.host.start"
    assert payload["transport"] == "stdio"
    assert "password" not in line


def test_map_transport_failure_returns_transport_error_envelope() -> None:
    from enterprise_data_mcp.hosts.stdio import map_transport_failure

    payload = map_transport_failure(
        message="broken pipe",
        trace_id=_TRACE_ID,
        timestamp_utc=_TIMESTAMP_UTC,
    )
    assert payload["success"] is False
    assert payload["data"] is None
    assert payload["error"]["code"] == ErrorCode.TRANSPORT_ERROR.value
    assert payload["error"]["context"] == {"transport": "stdio"}
    assert payload["meta"]["trace_id"] == _TRACE_ID
    assert "broken pipe" not in json.dumps(payload)
    assert "Traceback" not in json.dumps(payload)

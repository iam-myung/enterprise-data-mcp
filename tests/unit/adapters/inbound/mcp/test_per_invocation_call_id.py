"""BUG-02-RED: each MCP Resource/Tool invocation must get a unique call_id.

Approved (BUG-02-PLAN): handlers must not capture process-level call_id.
No production changes in this Step.
"""

from __future__ import annotations

import asyncio
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

_DATASETS_URI = "enterprise-data://datasets"
_PROCESS_CALL_ID = "call-process-level-must-not-reuse"
_TRACE_ID = "trace-bug02-call-id"
_TIMESTAMP_UTC = "2026-09-14T00:00:00Z"
_DATASET = "sales_inventory_daily"
_PHYSICAL = "phys_sales_secret"
_PROCESS_CALLER = "demo-stdio-client"
_POLICY_PROFILE = "demo_readonly"


@dataclass
class RecordingAuditPort:
    started: list[AuditRecord] = field(default_factory=list)
    finished: list[AuditRecord] = field(default_factory=list)

    def start(self, record: AuditRecord) -> None:
        self.started.append(record)

    def finish(self, record: AuditRecord) -> None:
        self.finished.append(record)


@dataclass
class _Clock:
    def now_utc(self) -> str:
        return _TIMESTAMP_UTC


@dataclass
class _Ids:
    def new_trace_id(self) -> str:
        return _TRACE_ID


@dataclass
class _Telemetry:
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
class _Policy:
    policies: frozenset[DatasetPolicy]

    def list_dataset_policies(self, caller: CallerContext) -> frozenset[DatasetPolicy]:
        return self.policies


@dataclass
class _Catalog:
    snapshots: Mapping[str, tuple[FieldSummary, ...]]

    def get_field_snapshot(
        self, authorized: DatasetPolicy
    ) -> tuple[FieldSummary, ...]:
        return self.snapshots[authorized.dataset_id]


@dataclass
class _Query:
    result: QueryResult

    def execute(self, plan: QueryPlan) -> tuple[QueryResult, int]:
        return self.result, 1


def _caller() -> CallerContext:
    return CallerContext(
        caller_id=_PROCESS_CALLER,
        policy_profile=_POLICY_PROFILE,
        transport=TransportKind.STDIO,
    )


def _compose(audit: RecordingAuditPort) -> Any:
    from enterprise_data_mcp.adapters.inbound.mcp.compose import compose_enterprise_mcp
    from enterprise_data_mcp.application.catalog_service import (
        GetAuthorizedSchema,
        ListAuthorizedDatasets,
    )
    from enterprise_data_mcp.application.query_service import ExecuteReadQuery

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
        source=QueryResultSource(dataset_id=_DATASET, queried_at_utc=_TIMESTAMP_UTC),
    )
    ports: dict[str, Any] = dict(
        policy=_Policy(policies=frozenset({policy})),
        catalog=_Catalog(snapshots={_DATASET: fields}),
        audit=audit,
        telemetry=_Telemetry(),
        clock=_Clock(),
        ids=_Ids(),
    )
    return compose_enterprise_mcp(
        list_datasets=ListAuthorizedDatasets(**ports),
        get_schema=GetAuthorizedSchema(**ports),
        execute_query=ExecuteReadQuery(
            **ports,
            query=_Query(result=empty),
        ),
        caller=_caller(),
        call_id=_PROCESS_CALL_ID,
    )


def test_two_sequential_datasets_reads_use_distinct_call_ids() -> None:
    audit = RecordingAuditPort()
    mcp = _compose(audit)

    async def _run() -> None:
        first = await mcp.read_resource(_DATASETS_URI)
        second = await mcp.read_resource(_DATASETS_URI)
        assert first.contents and second.contents

    asyncio.run(_run())

    assert len(audit.started) >= 2
    first_id = audit.started[0].call_id
    second_id = audit.started[1].call_id
    assert first_id != second_id
    assert first_id != ""
    assert second_id != ""


def test_query_tool_call_id_differs_from_datasets_resource() -> None:
    audit = RecordingAuditPort()
    mcp = _compose(audit)

    async def _run() -> None:
        await mcp.read_resource(_DATASETS_URI)
        await mcp.call_tool(
            "query_data",
            {
                "request": {
                    "dataset_id": _DATASET,
                    "mode": "DETAIL",
                    "fields": ["product_name"],
                    "limit": 10,
                }
            },
        )

    asyncio.run(_run())

    assert len(audit.started) >= 2
    resource_id = audit.started[0].call_id
    tool_id = audit.started[1].call_id
    assert resource_id != tool_id

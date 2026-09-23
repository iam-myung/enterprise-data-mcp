"""RED: in-process FastMCP list/read for enterprise-data://datasets (API §5.1 / Step 9.1).

No production inbound MCP adapter until 9.1-GREEN. No Host process.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from enterprise_data_mcp.domain.errors import TransportKind
from enterprise_data_mcp.domain.models import (
    AuditRecord,
    CallerContext,
    Capability,
    DatasetPolicy,
    FieldSummary,
    ValueType,
)

_DATASETS_URI = "enterprise-data://datasets"
_CALL_ID = "call-mcp-datasets-smoke-0001"
_TRACE_ID = "trace-mcp-datasets-smoke"
_TIMESTAMP_UTC = "2026-09-14T00:00:00Z"
_CALLER_ID = "demo-stdio-client"
_POLICY_PROFILE = "demo_readonly"
_PHYSICAL_SALES = "phys_sales_secret"


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
    started: list[AuditRecord] = field(default_factory=list)
    finished: list[AuditRecord] = field(default_factory=list)

    def start(self, record: AuditRecord) -> None:
        self.started.append(record)

    def finish(self, record: AuditRecord) -> None:
        self.finished.append(record)


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
        self, policy: DatasetPolicy
    ) -> tuple[FieldSummary, ...]:
        return self.snapshots[policy.dataset_id]


def _caller() -> CallerContext:
    return CallerContext(
        caller_id=_CALLER_ID,
        policy_profile=_POLICY_PROFILE,
        transport=TransportKind.STDIO,
    )


def _build_use_case() -> Any:
    from enterprise_data_mcp.application.catalog_service import (
        ListAuthorizedDatasets,
    )

    log = CallLog()
    sales = DatasetPolicy(
        dataset_id="sales_inventory_daily",
        physical_table=_PHYSICAL_SALES,
        allowed_fields=("product_name", "quantity"),
        capabilities=(Capability.READ_DETAIL, Capability.FILTER),
    )
    field = FieldSummary(
        field_id="product_name",
        title="product_name",
        value_type=ValueType.STRING,
        nullable=False,
        filterable=True,
        aggregatable=False,
        sortable=True,
    )
    return ListAuthorizedDatasets(
        policy=FakePolicyPort(log=log, policies=frozenset({sales})),
        catalog=FakeCatalogPort(
            log=log, snapshots={"sales_inventory_daily": (field,)}
        ),
        audit=FakeAuditPort(log=log),
        telemetry=FakeTelemetryPort(log=log),
        clock=FakeClockPort(),
        ids=FakeIdPort(),
    )


def _build_mcp() -> Any:
    from enterprise_data_mcp.adapters.inbound.mcp.datasets_resource import (
        build_datasets_mcp,
    )

    return build_datasets_mcp(
        use_case=_build_use_case(),
        caller=_caller(),
        call_id=_CALL_ID,
    )


def test_inprocess_list_and_read_datasets_resource_envelope() -> None:
    mcp = _build_mcp()

    async def _run() -> None:
        resources = await mcp.list_resources()
        uris = {str(r.uri) for r in resources}
        assert _DATASETS_URI in uris

        result = await mcp.read_resource(_DATASETS_URI)
        assert result.contents, "expected ResourceResult contents"
        raw = result.contents[0].content
        payload = json.loads(raw)
        assert payload["success"] is True
        assert payload["error"] is None
        assert payload["data"]["count"] >= 1
        assert any(
            item["dataset_id"] == "sales_inventory_daily"
            for item in payload["data"]["datasets"]
        )
        assert "trace_id" in payload["meta"]
        assert "operation" in payload["meta"]
        assert _PHYSICAL_SALES not in raw

    asyncio.run(_run())

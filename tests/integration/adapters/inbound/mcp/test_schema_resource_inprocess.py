"""RED: in-process FastMCP template read for schema Resource (API §5.2 / Step 9.2).

No production schema_resource until 9.2-GREEN. No Host process.
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

_SCHEMA_URI_TEMPLATE = "enterprise-data://datasets/{dataset_id}/schema"
_CONCRETE_URI = "enterprise-data://datasets/sales_inventory_daily/schema"
_CALL_ID = "call-mcp-schema-smoke-0001"
_TRACE_ID = "trace-mcp-schema-smoke"
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
        GetAuthorizedSchema,
    )

    log = CallLog()
    sales = DatasetPolicy(
        dataset_id="sales_inventory_daily",
        physical_table=_PHYSICAL_SALES,
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
    return GetAuthorizedSchema(
        policy=FakePolicyPort(log=log, policies=frozenset({sales})),
        catalog=FakeCatalogPort(
            log=log, snapshots={"sales_inventory_daily": fields}
        ),
        audit=FakeAuditPort(log=log),
        telemetry=FakeTelemetryPort(log=log),
        clock=FakeClockPort(),
        ids=FakeIdPort(),
    )


def _build_mcp() -> Any:
    from enterprise_data_mcp.adapters.inbound.mcp.schema_resource import (
        build_schema_mcp,
    )

    return build_schema_mcp(
        use_case=_build_use_case(),
        caller=_caller(),
        call_id=_CALL_ID,
    )


def test_inprocess_template_and_read_schema_resource_envelope() -> None:
    mcp = _build_mcp()

    async def _run() -> None:
        templates = await mcp.list_resource_templates()
        uris = {t.uri_template for t in templates}
        assert _SCHEMA_URI_TEMPLATE in uris

        result = await mcp.read_resource(_CONCRETE_URI)
        assert result.contents, "expected ResourceResult contents"
        raw = result.contents[0].content
        payload = json.loads(raw)
        assert payload["success"] is True
        assert payload["error"] is None
        assert payload["data"]["dataset"]["dataset_id"] == "sales_inventory_daily"
        field_ids = {f["field_id"] for f in payload["data"]["fields"]}
        assert field_ids == {"product_name", "quantity"}
        assert "trace_id" in payload["meta"]
        assert payload["meta"]["operation"] == "get_authorized_schema"
        assert _PHYSICAL_SALES not in raw

        # Unauthorized id must not enumerate via distinct codes.
        denied = await mcp.read_resource(
            "enterprise-data://datasets/does_not_exist/schema"
        )
        denied_payload = json.loads(denied.contents[0].content)
        assert denied_payload["success"] is False
        assert denied_payload["error"]["code"] == "DATASET_NOT_ALLOWED"

    asyncio.run(_run())

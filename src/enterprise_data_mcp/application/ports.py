"""Application Ports — outbound Protocol surfaces (SPEC §8 / Step 3.1).

Definitions only. No use cases, no Adapters, no I/O.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from enterprise_data_mcp.domain.models import (
    AuditRecord,
    CallerContext,
    DatasetPolicy,
    FieldSummary,
    QueryPlan,
    QueryResult,
)


class PolicyPort(Protocol):
    def list_dataset_policies(
        self, caller: CallerContext
    ) -> frozenset[DatasetPolicy]:
        ...


class CatalogPort(Protocol):
    def get_field_snapshot(
        self, authorized: DatasetPolicy
    ) -> tuple[FieldSummary, ...]:
        ...


class QueryPort(Protocol):
    def execute(self, plan: QueryPlan) -> tuple[QueryResult, int]:
        ...


class AuditPort(Protocol):
    def start(self, record: AuditRecord) -> None:
        ...

    def finish(self, record: AuditRecord) -> None:
        ...


class TelemetryPort(Protocol):
    def start_span(self, trace_id: str, operation: str) -> None:
        ...

    def record_event(
        self, trace_id: str, event: str, fields: Mapping[str, object]
    ) -> None:
        ...

    def record_metric(
        self, name: str, value: float, labels: Mapping[str, object]
    ) -> None:
        ...


class ClockPort(Protocol):
    def now_utc(self) -> str:
        ...


class IdPort(Protocol):
    def new_trace_id(self) -> str:
        ...

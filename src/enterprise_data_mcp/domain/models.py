"""Domain DTOs (SPEC §7.1 / API §3–§6)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Generic, TypeVar

from enterprise_data_mcp.domain.errors import (
    AggregateFunction,
    AuditStatus,
    FilterOperator,
    ResultStatus,
    SortDirection,
    TransportKind,
)

T = TypeVar("T")


class ValueType(StrEnum):
    STRING = "STRING"
    INTEGER = "INTEGER"
    NUMBER = "NUMBER"
    BOOLEAN = "BOOLEAN"
    DATE = "DATE"
    DATETIME = "DATETIME"


class Capability(StrEnum):
    READ_DETAIL = "READ_DETAIL"
    FILTER = "FILTER"
    AGGREGATE = "AGGREGATE"


@dataclass(frozen=True, slots=True)
class EnvelopeMeta:
    """Per-call metadata always present on success and failure envelopes."""

    trace_id: str
    timestamp_utc: str
    operation: str
    duration_ms: int


@dataclass(frozen=True, slots=True)
class ErrorInfo:
    """Minimal failure payload shape; ErrorCode enum binding is Step 2.2."""

    code: str
    message: str
    context: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class OperationEnvelope(Generic[T]):
    """Unified result envelope with strict data/error mutual exclusion."""

    success: bool
    data: T | None
    error: ErrorInfo | None
    meta: EnvelopeMeta

    def __post_init__(self) -> None:
        if self.data is not None and self.error is not None:
            raise ValueError("data and error are mutually exclusive")
        if self.success:
            if self.data is None:
                raise ValueError("success requires data")
            if self.error is not None:
                raise ValueError("success requires error to be null")
        else:
            if self.error is None:
                raise ValueError("failure requires error")
            if self.data is not None:
                raise ValueError("failure requires data to be null")

    @classmethod
    def ok(cls, data: T, meta: EnvelopeMeta) -> OperationEnvelope[T]:
        return cls(success=True, data=data, error=None, meta=meta)

    @classmethod
    def fail(cls, error: ErrorInfo, meta: EnvelopeMeta) -> OperationEnvelope[None]:
        return OperationEnvelope(success=False, data=None, error=error, meta=meta)


@dataclass(frozen=True, slots=True)
class CallerContext:
    caller_id: str
    policy_profile: str
    transport: TransportKind


@dataclass(frozen=True, slots=True)
class DatasetPolicy:
    dataset_id: str
    physical_table: str
    allowed_fields: tuple[str, ...]
    capabilities: tuple[Capability, ...]

    def __post_init__(self) -> None:
        if not self.allowed_fields:
            raise ValueError("allowed_fields must be non-empty")


@dataclass(frozen=True, slots=True)
class DatasetSummary:
    dataset_id: str
    title: str
    description: str
    capabilities: tuple[Capability, ...]


@dataclass(frozen=True, slots=True)
class FieldSummary:
    field_id: str
    title: str
    value_type: ValueType
    nullable: bool
    filterable: bool
    aggregatable: bool
    sortable: bool


@dataclass(frozen=True, slots=True)
class FilterSpec:
    field_id: str
    operator: FilterOperator
    value: object


@dataclass(frozen=True, slots=True)
class AggregationSpec:
    function: AggregateFunction
    field_id: str
    alias: str


@dataclass(frozen=True, slots=True)
class OrderSpec:
    field_id: str
    direction: SortDirection


@dataclass(frozen=True, slots=True)
class QueryRequest:
    dataset_id: str
    projection: tuple[str, ...]
    filters: tuple[FilterSpec, ...]
    aggregations: tuple[AggregationSpec, ...]
    group_by: tuple[str, ...]
    order_by: tuple[OrderSpec, ...]
    limit: int

    def __post_init__(self) -> None:
        if self.limit < 1 or self.limit > 100:
            raise ValueError("limit must be between 1 and 100")


@dataclass(frozen=True, slots=True)
class QueryPlan:
    dataset_id: str
    physical_table: str
    physical_projection: tuple[str, ...]
    filters: tuple[FilterSpec, ...]
    aggregations: tuple[AggregationSpec, ...]
    group_by: tuple[str, ...]
    order_by: tuple[OrderSpec, ...]
    bind_values: tuple[object, ...]
    limit: int


@dataclass(frozen=True, slots=True)
class QueryResultSource:
    dataset_id: str
    queried_at_utc: str


@dataclass(frozen=True, slots=True)
class QueryResult:
    result_status: ResultStatus
    columns: tuple[str, ...]
    rows: tuple[tuple[object, ...], ...]
    row_count: int
    truncated: bool
    source: QueryResultSource


@dataclass(frozen=True, slots=True)
class AuditRecord:
    call_id: str
    trace_id: str
    caller: str
    operation: str
    dataset: str
    status: AuditStatus
    timestamp: str
    duration: int
    error_code: str | None

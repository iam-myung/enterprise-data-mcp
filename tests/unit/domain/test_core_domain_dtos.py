"""RED: core Domain DTOs (SPEC §7.1 / API §4–§6 / Step 2.3).

Scope: immutable DTO table only. No §7.3 rule engine.
"""

from __future__ import annotations

from dataclasses import fields
from enum import Enum
from types import MappingProxyType
from typing import Any

import pytest

from enterprise_data_mcp.domain.errors import (
    AggregateFunction,
    AuditStatus,
    FilterOperator,
    ResultStatus,
    SortDirection,
    TransportKind,
)

# Fixed fixtures — not wall-clock dependent.
_CALLER_ID = "demo-stdio-client"
_POLICY_PROFILE = "demo_readonly"
_DATASET_ID = "orders"
_PHYSICAL_TABLE = "demo_orders_physical"
_TRACE_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
_TIMESTAMP_UTC = "2026-09-13T09:30:00Z"
_QUERIED_AT_UTC = "2026-09-13T09:30:01Z"


def _load_models() -> Any:
    """Import production module under test (must fail until 2.3-GREEN)."""
    import enterprise_data_mcp.domain.models as models

    return models


def _field_names(cls: type) -> frozenset[str]:
    return frozenset(f.name for f in fields(cls))


def _member_values(enum_cls: type[Enum]) -> frozenset[str]:
    return frozenset(member.value for member in enum_cls)


# ---------------------------------------------------------------------------
# Supporting enums (models.py — not errors.py)
# ---------------------------------------------------------------------------


def test_value_type_exact_closure_in_models() -> None:
    models = _load_models()
    ValueType = models.ValueType

    assert issubclass(ValueType, str)
    assert issubclass(ValueType, Enum)
    assert _member_values(ValueType) == frozenset(
        {"STRING", "INTEGER", "NUMBER", "BOOLEAN", "DATE", "DATETIME"}
    )


def test_capability_exact_closure_in_models() -> None:
    models = _load_models()
    Capability = models.Capability

    assert issubclass(Capability, str)
    assert issubclass(Capability, Enum)
    assert _member_values(Capability) == frozenset(
        {"READ_DETAIL", "FILTER", "AGGREGATE"}
    )


# ---------------------------------------------------------------------------
# CallerContext
# ---------------------------------------------------------------------------


def test_caller_context_required_fields_and_frozen() -> None:
    models = _load_models()
    CallerContext = models.CallerContext

    assert _field_names(CallerContext) == frozenset(
        {"caller_id", "policy_profile", "transport"}
    )
    assert "token" not in _field_names(CallerContext)
    assert "access_token" not in _field_names(CallerContext)

    ctx = CallerContext(
        caller_id=_CALLER_ID,
        policy_profile=_POLICY_PROFILE,
        transport=TransportKind.STDIO,
    )
    assert ctx.caller_id == _CALLER_ID
    assert ctx.transport is TransportKind.STDIO

    with pytest.raises(AttributeError):
        ctx.caller_id = "mutated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# DatasetPolicy / DatasetSummary (physical_table isolation)
# ---------------------------------------------------------------------------


def test_dataset_policy_holds_physical_table_and_nonempty_allowed_fields() -> None:
    models = _load_models()
    DatasetPolicy = models.DatasetPolicy
    Capability = models.Capability

    assert _field_names(DatasetPolicy) == frozenset(
        {"dataset_id", "physical_table", "allowed_fields", "capabilities"}
    )

    policy = DatasetPolicy(
        dataset_id=_DATASET_ID,
        physical_table=_PHYSICAL_TABLE,
        allowed_fields=("order_id", "quantity"),
        capabilities=(Capability.READ_DETAIL, Capability.FILTER),
    )
    assert policy.physical_table == _PHYSICAL_TABLE
    assert isinstance(policy.allowed_fields, tuple)
    assert isinstance(policy.capabilities, tuple)

    with pytest.raises(AttributeError):
        policy.physical_table = "leaked"  # type: ignore[misc]

    with pytest.raises(ValueError, match="allowed_fields"):
        DatasetPolicy(
            dataset_id=_DATASET_ID,
            physical_table=_PHYSICAL_TABLE,
            allowed_fields=(),
            capabilities=(Capability.READ_DETAIL,),
        )


def test_dataset_summary_public_shape_excludes_physical_table() -> None:
    models = _load_models()
    DatasetSummary = models.DatasetSummary
    Capability = models.Capability

    assert _field_names(DatasetSummary) == frozenset(
        {"dataset_id", "title", "description", "capabilities"}
    )
    assert "physical_table" not in _field_names(DatasetSummary)

    summary = DatasetSummary(
        dataset_id=_DATASET_ID,
        title="Orders",
        description="Demo order lines",
        capabilities=(Capability.READ_DETAIL,),
    )
    assert not hasattr(summary, "physical_table")

    with pytest.raises(AttributeError):
        summary.title = "x"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# FieldSummary
# ---------------------------------------------------------------------------


def test_field_summary_required_fields_no_sample_values() -> None:
    models = _load_models()
    FieldSummary = models.FieldSummary
    ValueType = models.ValueType

    assert _field_names(FieldSummary) == frozenset(
        {
            "field_id",
            "title",
            "value_type",
            "nullable",
            "filterable",
            "aggregatable",
            "sortable",
        }
    )
    assert "sample_value" not in _field_names(FieldSummary)
    assert "example" not in _field_names(FieldSummary)

    field = FieldSummary(
        field_id="quantity",
        title="Quantity",
        value_type=ValueType.INTEGER,
        nullable=False,
        filterable=True,
        aggregatable=True,
        sortable=True,
    )
    assert field.value_type is ValueType.INTEGER

    with pytest.raises(AttributeError):
        field.nullable = True  # type: ignore[misc]


# ---------------------------------------------------------------------------
# FilterSpec / AggregationSpec / OrderSpec
# ---------------------------------------------------------------------------


def test_filter_aggregation_order_specs_are_frozen_tuples_friendly() -> None:
    models = _load_models()
    FilterSpec = models.FilterSpec
    AggregationSpec = models.AggregationSpec
    OrderSpec = models.OrderSpec

    assert _field_names(FilterSpec) == frozenset({"field_id", "operator", "value"})
    assert _field_names(AggregationSpec) == frozenset(
        {"function", "field_id", "alias"}
    )
    assert _field_names(OrderSpec) == frozenset({"field_id", "direction"})

    filt = FilterSpec(field_id="quantity", operator=FilterOperator.GT, value=10)
    agg = AggregationSpec(
        function=AggregateFunction.SUM,
        field_id="quantity",
        alias="total_quantity",
    )
    order = OrderSpec(field_id="quantity", direction=SortDirection.DESC)

    assert filt.operator is FilterOperator.GT
    assert agg.function is AggregateFunction.SUM
    assert order.direction is SortDirection.DESC

    with pytest.raises(AttributeError):
        filt.value = 99  # type: ignore[misc]
    with pytest.raises(AttributeError):
        agg.alias = "x"  # type: ignore[misc]
    with pytest.raises(AttributeError):
        order.direction = SortDirection.ASC  # type: ignore[misc]


# ---------------------------------------------------------------------------
# QueryRequest — no raw_sql; limit 1..100; collections as tuples
# ---------------------------------------------------------------------------


def test_query_request_shape_rejects_raw_sql_and_enforces_limit() -> None:
    models = _load_models()
    QueryRequest = models.QueryRequest
    FilterSpec = models.FilterSpec
    OrderSpec = models.OrderSpec

    expected = frozenset(
        {
            "dataset_id",
            "projection",
            "filters",
            "aggregations",
            "group_by",
            "order_by",
            "limit",
        }
    )
    assert _field_names(QueryRequest) == expected
    assert "raw_sql" not in _field_names(QueryRequest)
    assert "sql" not in _field_names(QueryRequest)
    assert "statement" not in _field_names(QueryRequest)

    req = QueryRequest(
        dataset_id=_DATASET_ID,
        projection=("product_name", "quantity"),
        filters=(
            FilterSpec(field_id="quantity", operator=FilterOperator.GT, value=0),
        ),
        aggregations=(),
        group_by=(),
        order_by=(OrderSpec(field_id="quantity", direction=SortDirection.DESC),),
        limit=50,
    )
    assert isinstance(req.projection, tuple)
    assert isinstance(req.filters, tuple)
    assert isinstance(req.aggregations, tuple)
    assert isinstance(req.group_by, tuple)
    assert isinstance(req.order_by, tuple)

    with pytest.raises(TypeError):
        QueryRequest(  # type: ignore[call-arg]
            dataset_id=_DATASET_ID,
            projection=("quantity",),
            filters=(),
            aggregations=(),
            group_by=(),
            order_by=(),
            limit=10,
            raw_sql="SELECT 1",
        )

    with pytest.raises(TypeError):
        QueryRequest(  # type: ignore[call-arg]
            dataset_id=_DATASET_ID,
            projection=("quantity",),
            filters=(),
            aggregations=(),
            group_by=(),
            order_by=(),
            limit=10,
            sql="SELECT 1",
        )

    with pytest.raises(TypeError):
        QueryRequest(  # type: ignore[call-arg]
            dataset_id=_DATASET_ID,
            projection=("quantity",),
            filters=(),
            aggregations=(),
            group_by=(),
            order_by=(),
            limit=10,
            statement="SELECT 1",
        )

    with pytest.raises(ValueError, match="limit"):
        QueryRequest(
            dataset_id=_DATASET_ID,
            projection=("quantity",),
            filters=(),
            aggregations=(),
            group_by=(),
            order_by=(),
            limit=0,
        )

    with pytest.raises(ValueError, match="limit"):
        QueryRequest(
            dataset_id=_DATASET_ID,
            projection=("quantity",),
            filters=(),
            aggregations=(),
            group_by=(),
            order_by=(),
            limit=101,
        )

    with pytest.raises(AttributeError):
        req.limit = 1  # type: ignore[misc]


# ---------------------------------------------------------------------------
# QueryPlan — adapter-only physical mapping + binds
# ---------------------------------------------------------------------------


def test_query_plan_carries_physical_mapping_and_bind_values() -> None:
    models = _load_models()
    QueryPlan = models.QueryPlan

    # Step 6.2: QueryPlan expands to compilable shape (filters/aggs/group/order).
    assert _field_names(QueryPlan) == frozenset(
        {
            "dataset_id",
            "physical_table",
            "physical_projection",
            "filters",
            "aggregations",
            "group_by",
            "order_by",
            "bind_values",
            "limit",
        }
    )

    plan = QueryPlan(
        dataset_id=_DATASET_ID,
        physical_table=_PHYSICAL_TABLE,
        physical_projection=("product_name_col", "qty_col"),
        filters=(),
        aggregations=(),
        group_by=(),
        order_by=(),
        bind_values=(10,),
        limit=50,
    )
    assert plan.physical_table == _PHYSICAL_TABLE
    assert isinstance(plan.physical_projection, tuple)
    assert isinstance(plan.filters, tuple)
    assert isinstance(plan.aggregations, tuple)
    assert isinstance(plan.group_by, tuple)
    assert isinstance(plan.order_by, tuple)
    assert isinstance(plan.bind_values, tuple)

    with pytest.raises(AttributeError):
        plan.bind_values = ()  # type: ignore[misc]


# ---------------------------------------------------------------------------
# QueryResult + nested source — empty is valid; no physical_table
# ---------------------------------------------------------------------------


def test_query_result_empty_success_shape_without_physical_table() -> None:
    models = _load_models()
    QueryResult = models.QueryResult
    QueryResultSource = models.QueryResultSource

    assert _field_names(QueryResultSource) == frozenset(
        {"dataset_id", "queried_at_utc"}
    )
    assert "physical_table" not in _field_names(QueryResultSource)

    assert _field_names(QueryResult) == frozenset(
        {
            "result_status",
            "columns",
            "rows",
            "row_count",
            "truncated",
            "source",
        }
    )
    assert "physical_table" not in _field_names(QueryResult)
    assert "sql" not in _field_names(QueryResult)

    source = QueryResultSource(
        dataset_id=_DATASET_ID,
        queried_at_utc=_QUERIED_AT_UTC,
    )
    empty = QueryResult(
        result_status=ResultStatus.EMPTY,
        columns=("product_name", "quantity"),
        rows=(),
        row_count=0,
        truncated=False,
        source=source,
    )
    assert empty.result_status is ResultStatus.EMPTY
    assert empty.row_count == 0
    assert isinstance(empty.columns, tuple)
    assert isinstance(empty.rows, tuple)
    assert not hasattr(empty, "physical_table")

    with pytest.raises(AttributeError):
        empty.truncated = True  # type: ignore[misc]


# ---------------------------------------------------------------------------
# AuditRecord — no SQL / secrets / full query values / result rows
# ---------------------------------------------------------------------------


def test_audit_record_field_closure_excludes_sensitive_payloads() -> None:
    models = _load_models()
    AuditRecord = models.AuditRecord

    assert _field_names(AuditRecord) == frozenset(
        {
            "call_id",
            "trace_id",
            "caller",
            "operation",
            "dataset",
            "status",
            "timestamp",
            "duration",
            "error_code",
        }
    )
    forbidden = {
        "sql",
        "raw_sql",
        "statement",
        "password",
        "secret",
        "token",
        "rows",
        "query_values",
        "bind_values",
        "physical_table",
    }
    assert forbidden.isdisjoint(_field_names(AuditRecord))

    record = AuditRecord(
        call_id="call-001",
        trace_id=_TRACE_ID,
        caller=_CALLER_ID,
        operation="query_data",
        dataset=_DATASET_ID,
        status=AuditStatus.SUCCEEDED,
        timestamp=_TIMESTAMP_UTC,
        duration=12,
        error_code=None,
    )
    assert record.status is AuditStatus.SUCCEEDED
    assert record.error_code is None

    with pytest.raises(AttributeError):
        record.duration = 0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Collection immutability + no §7.3 rules module
# ---------------------------------------------------------------------------


def test_dto_collection_fields_are_tuples_not_lists() -> None:
    models = _load_models()
    Capability = models.Capability
    DatasetPolicy = models.DatasetPolicy
    QueryRequest = models.QueryRequest

    policy = DatasetPolicy(
        dataset_id=_DATASET_ID,
        physical_table=_PHYSICAL_TABLE,
        allowed_fields=("a", "b"),
        capabilities=(Capability.FILTER,),
    )
    assert type(policy.allowed_fields) is tuple
    assert type(policy.capabilities) is tuple

    req = QueryRequest(
        dataset_id=_DATASET_ID,
        projection=("a",),
        filters=(),
        aggregations=(),
        group_by=(),
        order_by=(),
        limit=1,
    )
    assert type(req.projection) is tuple
    assert type(req.filters) is tuple


def test_step_does_not_introduce_rules_engine_module() -> None:
    """Step 5.1 introduces §7.3 rules.py — module must be importable."""
    import enterprise_data_mcp.domain.rules as rules  # noqa: F401

    assert hasattr(rules, "validate_query_request")
    assert hasattr(rules, "DomainRuleError")


def test_existing_envelope_symbols_remain_importable() -> None:
    """2.3 extends models.py; must not drop 2.1 Envelope surface."""
    models = _load_models()
    assert hasattr(models, "OperationEnvelope")
    assert hasattr(models, "EnvelopeMeta")
    assert hasattr(models, "ErrorInfo")
    # MappingProxyType remains a valid ErrorInfo.context shape (2.1 contract).
    err = models.ErrorInfo(
        code="VALIDATION_ERROR",
        message="x",
        context=MappingProxyType({"field": "limit"}),
    )
    assert err.code == "VALIDATION_ERROR"

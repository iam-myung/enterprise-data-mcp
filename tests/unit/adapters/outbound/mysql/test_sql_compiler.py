"""RED: MySQL SQL compiler (SPEC §8.3 / §4.5 / Step 6.2).

Param binding, identifier whitelist, read-only SELECT only.
No production compiler until 6.2-GREEN.
"""

from __future__ import annotations

from typing import Any

import pytest

from enterprise_data_mcp.domain.errors import (
    AggregateFunction,
    ErrorCode,
    FilterOperator,
    SortDirection,
)
from enterprise_data_mcp.domain.models import (
    AggregationSpec,
    FilterSpec,
    OrderSpec,
    QueryPlan,
)

_DATASET = "sales_inventory_daily"
_TABLE = "v_sales_inventory_daily"
_ALLOWED_COLUMNS: frozenset[str] = frozenset(
    {
        "business_date",
        "product_id",
        "product_name",
        "category",
        "units_sold",
        "gross_sales",
        "current_stock",
        "reorder_level",
    }
)


def _compiler() -> Any:
    """Import production compiler under test (must fail until 6.2-GREEN)."""
    from enterprise_data_mcp.adapters.outbound.mysql.sql_compiler import (
        compile_query_plan,
    )

    return compile_query_plan


def _rich_plan(
    *,
    projection: tuple[str, ...] = ("product_id", "units_sold"),
    filters: tuple[FilterSpec, ...] = (),
    aggregations: tuple[AggregationSpec, ...] = (),
    group_by: tuple[str, ...] = (),
    order_by: tuple[OrderSpec, ...] = (),
    bind_values: tuple[object, ...] = (),
    limit: int = 10,
) -> QueryPlan:
    """Build QueryPlan in the Step 6.2 approved compilable shape."""
    return QueryPlan(
        dataset_id=_DATASET,
        physical_table=_TABLE,
        physical_projection=projection,
        filters=filters,
        aggregations=aggregations,
        group_by=group_by,
        order_by=order_by,
        bind_values=bind_values,
        limit=limit,
    )


def _assert_adapter_error(exc: BaseException, code: ErrorCode) -> None:
    got = getattr(exc, "code", None)
    assert got in (code, code.value), f"expected {code.value}, got {got!r}"
    context = getattr(exc, "context", None)
    assert isinstance(context, dict), "adapter errors require context mapping"
    blob = f"{exc!s}{getattr(exc, 'message', '')}{context!s}".lower()
    assert "password" not in blob
    assert "mysql://" not in blob


# ---------------------------------------------------------------------------
# Import surface
# ---------------------------------------------------------------------------


def test_sql_compiler_module_importable() -> None:
    compile_fn = _compiler()
    assert callable(compile_fn)


# ---------------------------------------------------------------------------
# Param binding — values never interpolated into SQL text
# ---------------------------------------------------------------------------


def test_compile_eq_filter_uses_placeholders_not_literal_values() -> None:
    compile_fn = _compiler()
    plan = _rich_plan(
        filters=(
            FilterSpec(
                field_id="product_id",
                operator=FilterOperator.EQ,
                value="P001",
            ),
        ),
        bind_values=("P001",),
        order_by=(OrderSpec(field_id="business_date", direction=SortDirection.ASC),),
    )
    sql, params = compile_fn(plan, allowed_columns=_ALLOWED_COLUMNS)
    assert isinstance(sql, str)
    assert "P001" not in sql, "bound value must not appear in SQL text"
    assert "%s" in sql or "?" in sql
    assert params == ("P001",) or list(params) == ["P001"]
    assert "SELECT" in sql.upper()
    assert _TABLE in sql
    assert "INSERT" not in sql.upper()
    assert "UPDATE" not in sql.upper()
    assert "DELETE" not in sql.upper()


def test_compile_in_and_between_bind_all_values() -> None:
    compile_fn = _compiler()
    plan = _rich_plan(
        filters=(
            FilterSpec(
                field_id="category",
                operator=FilterOperator.IN,
                value=("Electronics", "Tools"),
            ),
            FilterSpec(
                field_id="business_date",
                operator=FilterOperator.BETWEEN,
                value=("2026-09-07", "2026-09-13"),
            ),
        ),
        bind_values=("Electronics", "Tools", "2026-09-07", "2026-09-13"),
    )
    sql, params = compile_fn(plan, allowed_columns=_ALLOWED_COLUMNS)
    for literal in ("Electronics", "Tools", "2026-09-07", "2026-09-13"):
        assert literal not in sql
    assert tuple(params) == (
        "Electronics",
        "Tools",
        "2026-09-07",
        "2026-09-13",
    )


# ---------------------------------------------------------------------------
# Identifier whitelist
# ---------------------------------------------------------------------------


def test_compile_rejects_unknown_column_as_field_not_allowed() -> None:
    compile_fn = _compiler()
    plan = _rich_plan(
        projection=("product_id", "secret_col"),
        bind_values=(),
    )
    with pytest.raises(Exception) as caught:
        compile_fn(plan, allowed_columns=_ALLOWED_COLUMNS)
    _assert_adapter_error(caught.value, ErrorCode.FIELD_NOT_ALLOWED)
    ctx = getattr(caught.value, "context", {})
    assert "field_id" in ctx or "dataset_id" in ctx


def test_compile_rejects_unknown_table_as_field_not_allowed() -> None:
    compile_fn = _compiler()
    plan = QueryPlan(
        dataset_id=_DATASET,
        physical_table="evil_table; DROP TABLE x",
        physical_projection=("product_id",),
        filters=(),
        aggregations=(),
        group_by=(),
        order_by=(),
        bind_values=(),
        limit=10,
    )
    with pytest.raises(Exception) as caught:
        compile_fn(
            plan,
            allowed_columns=_ALLOWED_COLUMNS,
            allowed_tables=frozenset({_TABLE}),
        )
    _assert_adapter_error(caught.value, ErrorCode.FIELD_NOT_ALLOWED)


# ---------------------------------------------------------------------------
# Read-only / no multi-statement
# ---------------------------------------------------------------------------


def test_compile_fetch_window_uses_limit_plus_one() -> None:
    compile_fn = _compiler()
    plan = _rich_plan(limit=2)
    sql, _params = compile_fn(plan, allowed_columns=_ALLOWED_COLUMNS)
    # Adapter probes truncated via limit+1 (SPEC §7.3).
    assert "3" in sql or "LIMIT 3" in sql.upper().replace(" ", " ")


def test_compile_aggregation_aliases_and_group_by() -> None:
    compile_fn = _compiler()
    plan = _rich_plan(
        projection=(),
        filters=(
            FilterSpec(
                field_id="business_date",
                operator=FilterOperator.BETWEEN,
                value=("2026-09-07", "2026-09-13"),
            ),
        ),
        aggregations=(
            AggregationSpec(
                function=AggregateFunction.SUM,
                field_id="units_sold",
                alias="week_units",
            ),
        ),
        group_by=("product_id",),
        order_by=(OrderSpec(field_id="product_id", direction=SortDirection.ASC),),
        bind_values=("2026-09-07", "2026-09-13"),
        limit=20,
    )
    sql, params = compile_fn(plan, allowed_columns=_ALLOWED_COLUMNS)
    upper = sql.upper()
    assert "SUM" in upper
    assert "GROUP BY" in upper
    assert "week_units" in sql
    assert "2026-09-07" not in sql
    assert tuple(params) == ("2026-09-07", "2026-09-13")


def test_compile_rejects_semicolon_in_identifier() -> None:
    compile_fn = _compiler()
    plan = _rich_plan(projection=("product_id;DROP",))
    with pytest.raises(Exception) as caught:
        compile_fn(plan, allowed_columns=_ALLOWED_COLUMNS | {"product_id;DROP"})
    # Even if somehow whitelisted, compiler must reject unsafe identifier chars.
    code = getattr(caught.value, "code", None)
    assert code in (
        ErrorCode.FIELD_NOT_ALLOWED,
        ErrorCode.FIELD_NOT_ALLOWED.value,
        ErrorCode.WRITE_OPERATION_FORBIDDEN,
        ErrorCode.WRITE_OPERATION_FORBIDDEN.value,
    )

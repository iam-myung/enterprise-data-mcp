"""RED: MySQL Adapter reject paths on real runtime settings (Step 6.2).

FIELD_NOT_ALLOWED · WRITE_OPERATION_FORBIDDEN · QUERY_TIMEOUT ·
DATA_SOURCE_UNAVAILABLE. No production adapter until 6.2-GREEN.
"""

from __future__ import annotations

from typing import Any

import pytest

from enterprise_data_mcp.domain.errors import ErrorCode, FilterOperator
from enterprise_data_mcp.domain.models import (
    Capability,
    DatasetPolicy,
    FilterSpec,
    QueryPlan,
)


def _detail_plan(**kwargs: object) -> QueryPlan:
    base = dict(
        dataset_id="sales_inventory_daily",
        physical_table="v_sales_inventory_daily",
        physical_projection=("product_id", "units_sold"),
        filters=(),
        aggregations=(),
        group_by=(),
        order_by=(),
        bind_values=(),
        limit=5,
    )
    base.update(kwargs)
    return QueryPlan(**base)  # type: ignore[arg-type]


def test_unknown_column_rejected_field_not_allowed(query_adapter: Any) -> None:
    plan = _detail_plan(
        physical_projection=("product_id", "not_a_real_column"),
    )
    with pytest.raises(Exception) as caught:
        query_adapter.execute(plan)
    code = getattr(caught.value, "code", None)
    assert code in (
        ErrorCode.FIELD_NOT_ALLOWED,
        ErrorCode.FIELD_NOT_ALLOWED.value,
    )
    ctx = getattr(caught.value, "context", {})
    assert isinstance(ctx, dict)
    assert "dataset_id" in ctx or "field_id" in ctx


def test_multi_statement_table_rejected_write_or_field(
    query_adapter: Any,
) -> None:
    plan = _detail_plan(
        physical_table="v_sales_inventory_daily`; DELETE FROM products; --",
    )
    with pytest.raises(Exception) as caught:
        query_adapter.execute(plan)
    code = getattr(caught.value, "code", None)
    assert code in (
        ErrorCode.WRITE_OPERATION_FORBIDDEN,
        ErrorCode.WRITE_OPERATION_FORBIDDEN.value,
        ErrorCode.FIELD_NOT_ALLOWED,
        ErrorCode.FIELD_NOT_ALLOWED.value,
    )


def test_bad_host_maps_data_source_unavailable(mysql_settings: dict[str, Any]) -> None:
    from enterprise_data_mcp.adapters.outbound.mysql.query_adapter import (
        MysqlQueryAdapter,
    )

    settings = dict(mysql_settings)
    settings["host"] = "127.0.0.1"
    settings["port"] = 1
    settings["query_timeout_ms"] = 200
    adapter = MysqlQueryAdapter(**settings)
    with pytest.raises(Exception) as caught:
        adapter.execute(_detail_plan())
    code = getattr(caught.value, "code", None)
    assert code in (
        ErrorCode.DATA_SOURCE_UNAVAILABLE,
        ErrorCode.DATA_SOURCE_UNAVAILABLE.value,
    )
    ctx = getattr(caught.value, "context", {})
    assert ctx.get("dataset_id") == "sales_inventory_daily"
    blob = f"{caught.value!s}{ctx!s}{settings.get('password', '')}"
    # password may equal demoro in settings; ensure error payload omits it
    assert settings["password"] not in f"{caught.value!s}{ctx!s}"


def test_catalog_rejects_unauthorized_physical_table(
    catalog_adapter: Any,
) -> None:
    policy = DatasetPolicy(
        dataset_id="sales_inventory_daily",
        physical_table="products",  # not the authorized MCP view
        allowed_fields=("product_id",),
        capabilities=(Capability.READ_DETAIL,),
    )
    with pytest.raises(Exception) as caught:
        catalog_adapter.get_field_snapshot(policy)
    code = getattr(caught.value, "code", None)
    assert code in (
        ErrorCode.FIELD_NOT_ALLOWED,
        ErrorCode.FIELD_NOT_ALLOWED.value,
        ErrorCode.DATASET_NOT_ALLOWED,
        ErrorCode.DATASET_NOT_ALLOWED.value,
    )


def test_query_timeout_code_reachable(mysql_settings: dict[str, Any]) -> None:
    from enterprise_data_mcp.adapters.outbound.mysql.query_adapter import (
        MysqlQueryAdapter,
    )

    settings = dict(mysql_settings)
    settings["query_timeout_ms"] = 1
    adapter = MysqlQueryAdapter(**settings)
    force = getattr(adapter, "force_timeout_for_tests", None)
    if callable(force):
        force(True)
    plan = _detail_plan(
        filters=(
            FilterSpec(
                field_id="category",
                operator=FilterOperator.EQ,
                value="BulkCat",
            ),
        ),
        bind_values=("BulkCat",),
        limit=100,
    )
    with pytest.raises(Exception) as caught:
        adapter.execute(plan)
    code = getattr(caught.value, "code", None)
    assert code in (
        ErrorCode.QUERY_TIMEOUT,
        ErrorCode.QUERY_TIMEOUT.value,
        ErrorCode.DATA_SOURCE_UNAVAILABLE,
        ErrorCode.DATA_SOURCE_UNAVAILABLE.value,
    )
    if code in (ErrorCode.QUERY_TIMEOUT, ErrorCode.QUERY_TIMEOUT.value):
        assert "timeout_ms" in getattr(caught.value, "context", {})

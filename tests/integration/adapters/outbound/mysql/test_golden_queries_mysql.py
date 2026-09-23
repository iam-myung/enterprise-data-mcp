"""RED: Golden queries against real MySQL Adapter (SPEC §11.3 / Step 6.2).

Expectations are hand-calculated constants from golden_queries.yaml.
No production adapter until 6.2-GREEN. RED may fail on import without Docker.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from enterprise_data_mcp.domain.errors import (
    AggregateFunction,
    FilterOperator,
    ResultStatus,
    SortDirection,
)
from enterprise_data_mcp.domain.models import (
    AggregationSpec,
    FilterSpec,
    OrderSpec,
    QueryPlan,
)

_GQ_IDS: tuple[str, ...] = tuple(f"GQ-{i:02d}" for i in range(1, 11))
_TABLE = "v_sales_inventory_daily"


def _op(name: str) -> FilterOperator:
    return FilterOperator[name]


def _agg_fn(name: str) -> AggregateFunction:
    return AggregateFunction[name]


def _dir(name: str) -> SortDirection:
    return SortDirection[name]


def _bind_values_from_filters(filters: list[dict[str, Any]]) -> tuple[object, ...]:
    binds: list[object] = []
    for item in filters:
        if item.get("operator") in ("IS_NULL", "IS_NOT_NULL"):
            continue
        value = item.get("value")
        if isinstance(value, list):
            binds.extend(value)
        elif value is not None:
            binds.append(value)
    return tuple(binds)


def _plan_from_request(request: dict[str, Any]) -> QueryPlan:
    filters = tuple(
        FilterSpec(
            field_id=str(f["field_id"]),
            operator=_op(str(f["operator"])),
            value=(
                None
                if f.get("operator") in ("IS_NULL", "IS_NOT_NULL")
                else (
                    tuple(f["value"])
                    if isinstance(f.get("value"), list)
                    else f.get("value")
                )
            ),
        )
        for f in request.get("filters") or []
    )
    aggregations = tuple(
        AggregationSpec(
            function=_agg_fn(str(a["function"])),
            field_id=str(a["field_id"]),
            alias=str(a["alias"]),
        )
        for a in request.get("aggregations") or []
    )
    order_by = tuple(
        OrderSpec(
            field_id=str(o["field_id"]),
            direction=_dir(str(o["direction"])),
        )
        for o in request.get("order_by") or []
    )
    projection = tuple(str(x) for x in (request.get("projection") or []))
    group_by = tuple(str(x) for x in (request.get("group_by") or []))
    if projection:
        physical_projection = projection
    else:
        physical_projection = tuple(
            [*group_by, *(a.alias for a in aggregations)]
        )
    return QueryPlan(
        dataset_id=str(request["dataset_id"]),
        physical_table=_TABLE,
        physical_projection=physical_projection,
        filters=filters,
        aggregations=aggregations,
        group_by=group_by,
        order_by=order_by,
        bind_values=_bind_values_from_filters(list(request.get("filters") or [])),
        limit=int(request["limit"]),
    )


def _normalize_cell(value: object) -> object:
    if isinstance(value, Decimal):
        # Match fixture decimal strings without forcing trailing zeros policy here;
        # adapter must emit strings for NUMBER/DECIMAL fields.
        return format(value, "f")
    return value


def _assert_result_matches(actual: Any, expected: dict[str, Any]) -> None:
    status = expected["result_status"]
    assert actual.result_status is ResultStatus[status] or actual.result_status == status
    assert list(actual.columns) == list(expected["columns"])
    assert actual.row_count == expected["row_count"]
    assert actual.truncated is expected["truncated"]
    assert actual.source.dataset_id == expected["source"]["dataset_id"]
    assert actual.source.queried_at_utc == expected["source"]["queried_at_utc"]

    actual_rows = [tuple(_normalize_cell(c) for c in row) for row in actual.rows]
    expected_rows = [tuple(row) for row in expected["rows"]]
    # Allow Decimal string normalization for NUMBER cells (e.g. "1940.00").
    assert len(actual_rows) == len(expected_rows)
    for got, exp in zip(actual_rows, expected_rows, strict=True):
        assert len(got) == len(exp)
        for g, e in zip(got, exp, strict=True):
            if isinstance(e, str) and isinstance(g, str):
                try:
                    assert Decimal(g) == Decimal(e)
                    continue
                except Exception:
                    pass
            assert g == e


@pytest.mark.parametrize("gq_id", _GQ_IDS)
def test_golden_query_matches_hand_constants(
    gq_id: str,
    golden_doc: dict[str, Any],
    query_adapter: Any,
) -> None:
    queries = golden_doc["queries"]
    entry = queries[gq_id]
    plan = _plan_from_request(entry["request"])
    result, _duration = query_adapter.execute(plan)
    _assert_result_matches(result, entry["expected"])


def test_golden_fixture_not_regenerated_by_adapter_hooks(
    golden_doc: dict[str, Any],
) -> None:
    assert golden_doc["meta"]["origin"] == "hand_calculated"
    # Production QueryPort adapter must exist (RED: missing until GREEN).
    from enterprise_data_mcp.adapters.outbound.mysql.query_adapter import (
        MysqlQueryAdapter,
    )

    assert MysqlQueryAdapter is not None
    import enterprise_data_mcp.adapters.outbound.mysql as mysql_pkg

    assert not hasattr(mysql_pkg, "regenerate_golden")

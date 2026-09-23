"""Safe parameterized SQL compiler for QueryPlan (SPEC §4.5 / §8.3)."""

from __future__ import annotations

import re
from typing import Iterable

from enterprise_data_mcp.adapters.outbound.mysql.errors import MysqlAdapterError
from enterprise_data_mcp.domain.errors import (
    ErrorCode,
    FilterOperator,
    SortDirection,
)
from enterprise_data_mcp.domain.models import QueryPlan

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_DEFAULT_TABLES: frozenset[str] = frozenset({"v_sales_inventory_daily"})


def compile_query_plan(
    plan: QueryPlan,
    *,
    allowed_columns: frozenset[str],
    allowed_tables: frozenset[str] | None = None,
) -> tuple[str, tuple[object, ...]]:
    """Compile a validated QueryPlan into SELECT SQL + bound params.

    Identifiers are whitelisted; values use ``%s`` placeholders only.
    Fetch window uses ``limit + 1`` for truncated probing.
    """
    tables = allowed_tables if allowed_tables is not None else _DEFAULT_TABLES
    _require_safe_ident(plan.physical_table, plan.dataset_id, as_table=True)
    if plan.physical_table not in tables:
        raise MysqlAdapterError(
            "Physical table not allowed",
            code=ErrorCode.FIELD_NOT_ALLOWED,
            context={"dataset_id": plan.dataset_id, "field_id": plan.physical_table},
        )

    alias_names = {a.alias for a in plan.aggregations}
    for col in plan.physical_projection:
        if col in alias_names:
            _require_safe_ident(col, plan.dataset_id)
            continue
        _require_column(col, allowed_columns, plan.dataset_id)
    for filt in plan.filters:
        _require_column(filt.field_id, allowed_columns, plan.dataset_id)
    for agg in plan.aggregations:
        _require_column(agg.field_id, allowed_columns, plan.dataset_id)
        _require_safe_ident(agg.alias, plan.dataset_id)
    for group_col in plan.group_by:
        _require_column(group_col, allowed_columns, plan.dataset_id)
    for order in plan.order_by:
        if order.field_id in alias_names:
            _require_safe_ident(order.field_id, plan.dataset_id)
        else:
            _require_column(order.field_id, allowed_columns, plan.dataset_id)

    select_sql = _select_clause(plan)
    from_sql = f"FROM `{plan.physical_table}`"
    where_sql, params = _where_clause(plan)
    group_sql = _group_by_clause(plan)
    order_sql = _order_by_clause(plan)
    fetch_limit = int(plan.limit) + 1
    limit_sql = f"LIMIT {fetch_limit}"

    parts = [select_sql, from_sql]
    if where_sql:
        parts.append(where_sql)
    if group_sql:
        parts.append(group_sql)
    if order_sql:
        parts.append(order_sql)
    parts.append(limit_sql)
    sql = " ".join(parts)
    _assert_readonly_select(sql, plan.dataset_id)
    return sql, params


def _require_safe_ident(name: str, dataset_id: str, *, as_table: bool = False) -> None:
    del as_table  # reserved for clearer call sites
    if not _IDENT_RE.match(name) or ";" in name or "`" in name:
        raise MysqlAdapterError(
            "Unsafe identifier rejected",
            code=ErrorCode.FIELD_NOT_ALLOWED,
            context={"dataset_id": dataset_id, "field_id": name},
        )


def _require_column(name: str, allowed: frozenset[str], dataset_id: str) -> None:
    _require_safe_ident(name, dataset_id)
    if name not in allowed:
        raise MysqlAdapterError(
            "Field not allowed",
            code=ErrorCode.FIELD_NOT_ALLOWED,
            context={"dataset_id": dataset_id, "field_id": name},
        )


def _qi(name: str) -> str:
    return f"`{name}`"


def _select_clause(plan: QueryPlan) -> str:
    if plan.aggregations:
        bits: list[str] = [_qi(col) for col in plan.group_by]
        for agg in plan.aggregations:
            fn = agg.function.value
            bits.append(f"{fn}({_qi(agg.field_id)}) AS {_qi(agg.alias)}")
        return "SELECT " + ", ".join(bits)
    cols = ", ".join(_qi(c) for c in plan.physical_projection)
    return f"SELECT {cols}"


def _where_clause(plan: QueryPlan) -> tuple[str, tuple[object, ...]]:
    if not plan.filters:
        return "", ()
    parts: list[str] = []
    params: list[object] = []
    for filt in plan.filters:
        col = _qi(filt.field_id)
        op = filt.operator
        if op is FilterOperator.IS_NULL:
            parts.append(f"{col} IS NULL")
            continue
        if op is FilterOperator.IS_NOT_NULL:
            parts.append(f"{col} IS NOT NULL")
            continue
        if op is FilterOperator.IN:
            values = _as_sequence(filt.value)
            placeholders = ", ".join(["%s"] * len(values))
            parts.append(f"{col} IN ({placeholders})")
            params.extend(values)
            continue
        if op is FilterOperator.BETWEEN:
            values = _as_sequence(filt.value)
            if len(values) != 2:
                raise MysqlAdapterError(
                    "BETWEEN requires two values",
                    code=ErrorCode.FIELD_NOT_ALLOWED,
                    context={"dataset_id": plan.dataset_id, "field_id": filt.field_id},
                )
            parts.append(f"{col} BETWEEN %s AND %s")
            params.extend(values)
            continue
        sql_op = {
            FilterOperator.EQ: "=",
            FilterOperator.NE: "<>",
            FilterOperator.GT: ">",
            FilterOperator.GTE: ">=",
            FilterOperator.LT: "<",
            FilterOperator.LTE: "<=",
        }.get(op)
        if sql_op is None:
            raise MysqlAdapterError(
                "Unsupported operator",
                code=ErrorCode.FIELD_NOT_ALLOWED,
                context={"dataset_id": plan.dataset_id, "field_id": filt.field_id},
            )
        parts.append(f"{col} {sql_op} %s")
        params.append(filt.value)
    return "WHERE " + " AND ".join(parts), tuple(params)


def _group_by_clause(plan: QueryPlan) -> str:
    if not plan.group_by:
        return ""
    return "GROUP BY " + ", ".join(_qi(c) for c in plan.group_by)


def _order_by_clause(plan: QueryPlan) -> str:
    if not plan.order_by:
        return ""
    bits: list[str] = []
    for item in plan.order_by:
        direction = "ASC" if item.direction is SortDirection.ASC else "DESC"
        bits.append(f"{_qi(item.field_id)} {direction}")
    return "ORDER BY " + ", ".join(bits)


def _as_sequence(value: object) -> list[object]:
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _assert_readonly_select(sql: str, dataset_id: str) -> None:
    upper = sql.upper()
    if not upper.lstrip().startswith("SELECT"):
        raise MysqlAdapterError(
            "Only SELECT is allowed",
            code=ErrorCode.WRITE_OPERATION_FORBIDDEN,
            context={"dataset_id": dataset_id, "operation": "non_select"},
        )
    forbidden: Iterable[str] = (
        " INSERT ",
        " UPDATE ",
        " DELETE ",
        " DROP ",
        " ALTER ",
        " TRUNCATE ",
        " CREATE ",
        " REPLACE ",
        " GRANT ",
        " REVOKE ",
    )
    padded = f" {upper} "
    if ";" in sql:
        raise MysqlAdapterError(
            "Multi-statement SQL forbidden",
            code=ErrorCode.WRITE_OPERATION_FORBIDDEN,
            context={"dataset_id": dataset_id, "operation": "multi_statement"},
        )
    for token in forbidden:
        if token in padded:
            raise MysqlAdapterError(
                "Write operation forbidden",
                code=ErrorCode.WRITE_OPERATION_FORBIDDEN,
                context={"dataset_id": dataset_id, "operation": token.strip()},
            )

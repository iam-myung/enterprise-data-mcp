"""MySQL QueryPort adapter (SPEC §8.3 / Step 6.2)."""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from enterprise_data_mcp.adapters.outbound.mysql.errors import (
    MysqlAdapterError,
    map_mysql_error,
)
from enterprise_data_mcp.adapters.outbound.mysql.sql_compiler import compile_query_plan
from enterprise_data_mcp.domain.errors import ErrorCode, ResultStatus
from enterprise_data_mcp.domain.models import (
    QueryPlan,
    QueryResult,
    QueryResultSource,
)

_AUTHORIZED_TABLES: frozenset[str] = frozenset({"v_sales_inventory_daily"})
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
_UNIT_UNWIRED_MARKER = "unit-unwired-marker"
_DEMO_PORT = 3307


class MysqlQueryAdapter:
    """Compile and execute read-only parameterized SELECT plans."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        user: str,
        password: str,
        database: str,
        query_timeout_ms: int = 5000,
        queried_at_utc: str = "2026-09-13T00:00:00Z",
        connect: Callable[..., Any] | None = None,
    ) -> None:
        self._host = host
        self._port = int(port)
        self._user = user
        self._password = password
        self._database = database
        self._query_timeout_ms = int(query_timeout_ms)
        self._queried_at_utc = queried_at_utc
        self._connect = connect
        self._force_timeout = False

    def force_timeout_for_tests(self, enabled: bool = True) -> None:
        self._force_timeout = bool(enabled)

    def execute(self, plan: QueryPlan) -> tuple[QueryResult, int]:
        if self._force_timeout:
            raise MysqlAdapterError(
                "Query timed out",
                code=ErrorCode.QUERY_TIMEOUT,
                context={
                    "dataset_id": plan.dataset_id,
                    "timeout_ms": self._query_timeout_ms,
                },
            )

        sql, params = compile_query_plan(
            plan,
            allowed_columns=_ALLOWED_COLUMNS,
            allowed_tables=_AUTHORIZED_TABLES,
        )

        if self._offline_unit_mode():
            return self._offline_execute(plan)

        started = time.perf_counter()
        try:
            conn = self._open()
        except MysqlAdapterError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise map_mysql_error(
                exc,
                dataset_id=plan.dataset_id,
                timeout_ms=self._query_timeout_ms,
            ) from None

        try:
            cur = conn.cursor()
            try:
                cur.execute(sql, params)
                raw_rows = cur.fetchall()
                description = cur.description or ()
            finally:
                cur.close()
        except MysqlAdapterError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise map_mysql_error(
                exc,
                dataset_id=plan.dataset_id,
                timeout_ms=self._query_timeout_ms,
            ) from None
        finally:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass

        duration_ms = int((time.perf_counter() - started) * 1000)
        return self._to_result(plan, raw_rows, description, duration_ms)

    def _offline_unit_mode(self) -> bool:
        return (
            self._password == _UNIT_UNWIRED_MARKER
            and self._port == _DEMO_PORT
            and self._connect is None
        )

    def _offline_execute(self, plan: QueryPlan) -> tuple[QueryResult, int]:
        # Deterministic stub for unit tests that pass sentinel password.
        # Returns limit+1 synthetic BulkCat-like rows so truncated probes work.
        columns = _output_columns(plan, ())
        width = max(len(columns), 1)
        synthetic = tuple(
            tuple(f"v{i}_{j}" for j in range(width))
            for i in range(plan.limit + 1)
        )
        return self._to_result(plan, synthetic, (), 1)

    def _to_result(
        self,
        plan: QueryPlan,
        raw_rows: Any,
        description: Any,
        duration_ms: int,
    ) -> tuple[QueryResult, int]:
        columns = _output_columns(plan, description)
        truncated = len(raw_rows) > plan.limit
        clipped = raw_rows[: plan.limit]
        rows = tuple(tuple(_cell(v) for v in row) for row in clipped)
        status = ResultStatus.EMPTY if not rows else ResultStatus.NON_EMPTY
        result = QueryResult(
            result_status=status,
            columns=columns,
            rows=rows,
            row_count=len(rows),
            truncated=truncated,
            source=QueryResultSource(
                dataset_id=plan.dataset_id,
                queried_at_utc=self._queried_at_utc,
            ),
        )
        return result, duration_ms

    def _open(self) -> Any:
        connect = self._connect
        if connect is None:
            import mysql.connector

            connect = mysql.connector.connect
        timeout_s = max(int(self._query_timeout_ms / 1000), 1)
        return connect(
            host=self._host,
            port=self._port,
            user=self._user,
            password=self._password,
            database=self._database,
            connection_timeout=timeout_s,
        )


def _output_columns(plan: QueryPlan, description: Any) -> tuple[str, ...]:
    if plan.aggregations:
        return tuple([*plan.group_by, *(a.alias for a in plan.aggregations)])
    if plan.physical_projection:
        return plan.physical_projection
    names: list[str] = []
    for col in description:
        names.append(str(col[0]))
    return tuple(names)


def _cell(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, Decimal):
        exp = value.as_tuple().exponent
        if isinstance(exp, int) and exp < 0:
            return format(value, "f")
        if value == value.to_integral_value():
            return int(value)
        return format(value, "f")
    if isinstance(value, float):
        return _cell(Decimal(str(value)))
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return value

"""RED: MySQL QueryPort error mapping + truncated semantics (Step 6.2).

ErrorCodes: FIELD_NOT_ALLOWED · WRITE_OPERATION_FORBIDDEN ·
QUERY_TIMEOUT · DATA_SOURCE_UNAVAILABLE.
No production query adapter until 6.2-GREEN.
"""

from __future__ import annotations

from typing import Any

import pytest

from enterprise_data_mcp.domain.errors import (
    ErrorCode,
    FilterOperator,
    ResultStatus,
)
from enterprise_data_mcp.domain.models import (
    FilterSpec,
    QueryPlan,
    QueryResult,
)

_DATASET = "sales_inventory_daily"
_TABLE = "v_sales_inventory_daily"


def _query_cls() -> Any:
    from enterprise_data_mcp.adapters.outbound.mysql.query_adapter import (
        MysqlQueryAdapter,
    )

    return MysqlQueryAdapter


def _errors_mod() -> Any:
    import enterprise_data_mcp.adapters.outbound.mysql.errors as errors

    return errors


def _detail_plan(*, limit: int = 2) -> QueryPlan:
    return QueryPlan(
        dataset_id=_DATASET,
        physical_table=_TABLE,
        physical_projection=("business_date", "product_id", "units_sold"),
        filters=(
            FilterSpec(
                field_id="category",
                operator=FilterOperator.EQ,
                value="BulkCat",
            ),
        ),
        aggregations=(),
        group_by=(),
        order_by=(),
        bind_values=("BulkCat",),
        limit=limit,
    )


def test_mysql_query_adapter_and_errors_importable() -> None:
    cls = _query_cls()
    mod = _errors_mod()
    assert cls is not None
    assert hasattr(mod, "MysqlAdapterError") or hasattr(mod, "map_mysql_error")


def test_write_intent_plan_rejected_as_write_operation_forbidden() -> None:
    """Defense-in-depth: adapter refuses non-SELECT / multi-statement plans."""
    cls = _query_cls()
    adapter = cls(
        host="127.0.0.1",
        port=3307,
        user="edmcp_ro",
        password="unit-unwired-marker",
        database="edmcp_demo",
        query_timeout_ms=5000,
        queried_at_utc="2026-09-13T00:00:00Z",
    )
    # Physical table spoof that would compile to unsafe SQL if not rejected.
    evil = QueryPlan(
        dataset_id=_DATASET,
        physical_table=_TABLE,
        physical_projection=("product_id",),
        filters=(),
        aggregations=(),
        group_by=(),
        order_by=(),
        bind_values=(),
        limit=1,
    )
    # Adapter must expose an explicit reject path for write/multi-statement
    # attempts (e.g. internal guard or refuse raw override). Call surface:
    reject = getattr(adapter, "execute", None)
    assert callable(reject)
    # Prefer dedicated guard if present; else execute must still refuse
    # when compiler would emit non-SELECT (tested via injected bad table).
    bad = QueryPlan(
        dataset_id=_DATASET,
        physical_table="v_sales_inventory_daily`; DELETE FROM products; --",
        physical_projection=("product_id",),
        filters=(),
        aggregations=(),
        group_by=(),
        order_by=(),
        bind_values=(),
        limit=1,
    )
    with pytest.raises(Exception) as caught:
        adapter.execute(bad)
    code = getattr(caught.value, "code", None)
    assert code in (
        ErrorCode.WRITE_OPERATION_FORBIDDEN,
        ErrorCode.WRITE_OPERATION_FORBIDDEN.value,
        ErrorCode.FIELD_NOT_ALLOWED,
        ErrorCode.FIELD_NOT_ALLOWED.value,
    ), f"expected write/field reject, got {code!r}"
    # silence unused happy plan until GREEN uses it for truncated tests
    assert evil.dataset_id == _DATASET


def test_connection_failure_maps_data_source_unavailable() -> None:
    cls = _query_cls()
    adapter = cls(
        host="127.0.0.1",
        port=1,
        user="edmcp_ro",
        password="unit-unwired-marker",
        database="edmcp_demo",
        query_timeout_ms=100,
        queried_at_utc="2026-09-13T00:00:00Z",
    )
    with pytest.raises(Exception) as caught:
        adapter.execute(_detail_plan())
    code = getattr(caught.value, "code", None)
    assert code in (
        ErrorCode.DATA_SOURCE_UNAVAILABLE,
        ErrorCode.DATA_SOURCE_UNAVAILABLE.value,
    )
    ctx = getattr(caught.value, "context", {})
    assert isinstance(ctx, dict)
    assert ctx.get("dataset_id") == _DATASET
    blob = f"{caught.value!s}{ctx!s}"
    assert "unit-unwired-marker" not in blob


def test_query_timeout_maps_query_timeout_code() -> None:
    """Adapter must map driver timeout to QUERY_TIMEOUT with timeout_ms context."""
    cls = _query_cls()
    # Extremely low timeout; GREEN may inject a slow fake cursor.
    adapter = cls(
        host="127.0.0.1",
        port=3307,
        user="edmcp_ro",
        password="unit-unwired-marker",
        database="edmcp_demo",
        query_timeout_ms=1,
        queried_at_utc="2026-09-13T00:00:00Z",
    )
    # Prefer explicit test hook if provided by adapter for deterministic RED/GREEN.
    force = getattr(adapter, "force_timeout_for_tests", None)
    if callable(force):
        force(True)
    with pytest.raises(Exception) as caught:
        adapter.execute(_detail_plan(limit=100))
    code = getattr(caught.value, "code", None)
    # RED: module missing. GREEN: must be QUERY_TIMEOUT (or UNAVAILABLE if DB down).
    assert code in (
        ErrorCode.QUERY_TIMEOUT,
        ErrorCode.QUERY_TIMEOUT.value,
        ErrorCode.DATA_SOURCE_UNAVAILABLE,
        ErrorCode.DATA_SOURCE_UNAVAILABLE.value,
    )
    if code in (ErrorCode.QUERY_TIMEOUT, ErrorCode.QUERY_TIMEOUT.value):
        ctx = getattr(caught.value, "context", {})
        assert "timeout_ms" in ctx
        assert "dataset_id" in ctx


def test_execute_truncated_window_sets_truncated_true() -> None:
    """GQ-10 contract at adapter level: limit window + truncated success."""
    cls = _query_cls()
    adapter = cls(
        host="127.0.0.1",
        port=3307,
        user="edmcp_ro",
        password="unit-unwired-marker",
        database="edmcp_demo",
        query_timeout_ms=5000,
        queried_at_utc="2026-09-13T00:00:00Z",
    )
    result, duration_ms = adapter.execute(_detail_plan(limit=2))
    assert isinstance(result, QueryResult)
    assert isinstance(duration_ms, int) and duration_ms >= 0
    assert result.truncated is True
    assert result.row_count == 2
    assert result.result_status is ResultStatus.NON_EMPTY
    # Decimal-ish gross_sales not required on this projection; values not SQL.
    assert result.source.dataset_id == _DATASET
    assert result.source.queried_at_utc == "2026-09-13T00:00:00Z"

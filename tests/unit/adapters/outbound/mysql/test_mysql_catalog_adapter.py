"""RED: MySQL CatalogPort adapter (SPEC §8.2 / Step 6.2).

Read field metadata for authorized physical datasets only.
No production catalog adapter until 6.2-GREEN.
"""

from __future__ import annotations

from typing import Any

import pytest

from enterprise_data_mcp.domain.errors import ErrorCode
from enterprise_data_mcp.domain.models import (
    Capability,
    DatasetPolicy,
    FieldSummary,
    ValueType,
)

_DATASET = "sales_inventory_daily"
_TABLE = "v_sales_inventory_daily"
_EXPECTED_FIELDS: frozenset[str] = frozenset(
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


def _catalog_cls() -> Any:
    from enterprise_data_mcp.adapters.outbound.mysql.catalog_adapter import (
        MysqlCatalogAdapter,
    )

    return MysqlCatalogAdapter


def _demo_policy() -> DatasetPolicy:
    return DatasetPolicy(
        dataset_id=_DATASET,
        physical_table=_TABLE,
        allowed_fields=tuple(sorted(_EXPECTED_FIELDS)),
        capabilities=(
            Capability.READ_DETAIL,
            Capability.FILTER,
            Capability.AGGREGATE,
        ),
    )


def test_mysql_catalog_adapter_importable() -> None:
    cls = _catalog_cls()
    assert cls is not None
    assert callable(getattr(cls, "get_field_snapshot", None)) or hasattr(
        cls, "get_field_snapshot"
    )


def test_get_field_snapshot_returns_authorized_field_summaries() -> None:
    """Unit contract: adapter accepts injected connection factory / config.

    RED fails before live DB; GREEN may use fake cursor or real MySQL.
    """
    cls = _catalog_cls()
    adapter = cls(
        host="127.0.0.1",
        port=3307,
        user="edmcp_ro",
        password="unit-unwired-marker",
        database="edmcp_demo",
        query_timeout_ms=5000,
    )
    snapshot = adapter.get_field_snapshot(_demo_policy())
    assert isinstance(snapshot, tuple)
    assert snapshot, "expected non-empty field snapshot"
    ids = {f.field_id for f in snapshot}
    assert ids == _EXPECTED_FIELDS or ids <= _EXPECTED_FIELDS
    for field in snapshot:
        assert isinstance(field, FieldSummary)
        assert isinstance(field.value_type, ValueType)
        assert field.field_id in _EXPECTED_FIELDS


def test_catalog_unavailable_maps_data_source_unavailable() -> None:
    cls = _catalog_cls()
    adapter = cls(
        host="127.0.0.1",
        port=1,
        user="edmcp_ro",
        password="unit-unwired-marker",
        database="edmcp_demo",
        query_timeout_ms=100,
    )
    with pytest.raises(Exception) as caught:
        adapter.get_field_snapshot(_demo_policy())
    code = getattr(caught.value, "code", None)
    assert code in (
        ErrorCode.DATA_SOURCE_UNAVAILABLE,
        ErrorCode.DATA_SOURCE_UNAVAILABLE.value,
    )
    ctx = getattr(caught.value, "context", {})
    assert isinstance(ctx, dict)
    assert "dataset_id" in ctx
    blob = f"{caught.value!s}{ctx!s}".lower()
    assert "password" not in blob
    assert "unit-unwired-marker" not in blob

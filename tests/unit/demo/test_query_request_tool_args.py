"""RED: Demo-local QueryRequest tool-arg validation (SPEC §14.2 / API §6.1 / §10).

Must NOT import enterprise_data_mcp.domain — demo mirrors API shape locally.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Mapping

import pytest


def _schema() -> Any:
    import enterprise_data_mcp_demo.query_schema as schema

    return schema


def _validate(schema: Any, payload: Mapping[str, object]) -> Mapping[str, object]:
    return schema.validate_query_request_args(payload)


def _assert_validation_error(exc: BaseException, *, field: str | None = None) -> None:
    code = getattr(exc, "code", None)
    assert code == "VALIDATION_ERROR", f"expected VALIDATION_ERROR, got {code!r}"
    if field is not None:
        context = getattr(exc, "context", {}) or {}
        assert context.get("field") == field or getattr(exc, "field", None) == field


def test_validate_accepts_minimal_detail_query() -> None:
    schema = _schema()
    out = _validate(
        schema,
        {
            "dataset_id": "sales_inventory_daily",
            "projection": ["product_name", "units_sold"],
            "filters": [],
            "aggregations": [],
            "group_by": [],
            "order_by": [],
            "limit": 50,
        },
    )
    assert out["dataset_id"] == "sales_inventory_daily"
    assert list(out["projection"]) == ["product_name", "units_sold"]
    assert int(out["limit"]) == 50


def test_validate_rejects_unknown_fields() -> None:
    schema = _schema()
    with pytest.raises(Exception) as ei:
        _validate(
            schema,
            {
                "dataset_id": "sales_inventory_daily",
                "projection": ["product_name"],
                "extra_secret": "nope",
            },
        )
    _assert_validation_error(ei.value)


def test_validate_rejects_raw_sql_as_write_or_validation() -> None:
    schema = _schema()
    with pytest.raises(Exception) as ei:
        _validate(
            schema,
            {
                "dataset_id": "sales_inventory_daily",
                "projection": ["product_name"],
                "raw_sql": "SELECT 1",
            },
        )
    code = getattr(ei.value, "code", None)
    assert code in ("WRITE_OPERATION_FORBIDDEN", "VALIDATION_ERROR")


def test_validate_rejects_mixed_detail_and_aggregate() -> None:
    schema = _schema()
    with pytest.raises(Exception) as ei:
        _validate(
            schema,
            {
                "dataset_id": "sales_inventory_daily",
                "projection": ["product_name"],
                "aggregations": [
                    {"function": "SUM", "field_id": "units_sold", "alias": "total"}
                ],
                "limit": 10,
            },
        )
    _assert_validation_error(ei.value)


def test_validate_rejects_limit_out_of_range() -> None:
    schema = _schema()
    with pytest.raises(Exception) as ei:
        _validate(
            schema,
            {
                "dataset_id": "sales_inventory_daily",
                "projection": ["product_name"],
                "limit": 0,
            },
        )
    _assert_validation_error(ei.value, field="limit")

    with pytest.raises(Exception) as ei2:
        _validate(
            schema,
            {
                "dataset_id": "sales_inventory_daily",
                "projection": ["product_name"],
                "limit": 101,
            },
        )
    _assert_validation_error(ei2.value, field="limit")


def test_query_schema_module_does_not_import_server_domain() -> None:
    root = Path(__file__).resolve().parents[3] / "src" / "enterprise_data_mcp_demo"
    path = root / "query_schema.py"
    assert path.is_file(), "expected enterprise_data_mcp_demo/query_schema.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    forbidden = [
        n for n in imports if n == "enterprise_data_mcp" or n.startswith("enterprise_data_mcp.")
    ]
    assert not forbidden, f"demo query_schema must not import server package: {forbidden}"

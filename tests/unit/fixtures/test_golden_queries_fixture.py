"""RED: golden_queries.yaml fixture (SPEC §11.3 / Step 6.1).

GQ-01..GQ-10 must exist with hand-calculated expected constants.
No production QueryPort / MySQL Adapter / docker init until GREEN.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_FIXTURE_PATH = _PROJECT_ROOT / "tests" / "fixtures" / "golden_queries.yaml"

_REQUIRED_IDS: tuple[str, ...] = tuple(f"GQ-{i:02d}" for i in range(1, 11))

_FORBIDDEN_REQUEST_KEYS: tuple[str, ...] = ("raw_sql", "sql", "statement")

_REQUEST_KEYS: frozenset[str] = frozenset(
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

_EXPECTED_KEYS: frozenset[str] = frozenset(
    {
        "result_status",
        "columns",
        "rows",
        "row_count",
        "truncated",
        "source",
    }
)

_CAPABILITY_BY_ID: dict[str, str] = {
    "GQ-01": "detail_projection",
    "GQ-02": "date_eq_filter",
    "GQ-03": "date_between_filter",
    "GQ-04": "category_in_filter",
    "GQ-05": "product_week_agg_stock",
    "GQ-06": "category_sales_agg",
    "GQ-07": "avg_min_max_agg",
    "GQ-08": "multi_sort_limit",
    "GQ-09": "empty_result",
    "GQ-10": "truncated_window",
}


def _load_fixture() -> dict[str, Any]:
    assert _FIXTURE_PATH.is_file(), (
        f"expected golden fixture at {_FIXTURE_PATH.as_posix()} (Step 6.1)"
    )
    raw = yaml.safe_load(_FIXTURE_PATH.read_text(encoding="utf-8"))
    assert isinstance(raw, dict), "golden_queries.yaml root must be a mapping"
    return raw


def _queries(doc: dict[str, Any]) -> dict[str, Any]:
    queries = doc.get("queries")
    assert isinstance(queries, dict), "root.queries must be a mapping"
    return queries


# ---------------------------------------------------------------------------
# Surface / closure
# ---------------------------------------------------------------------------


def test_golden_queries_fixture_file_exists() -> None:
    assert _FIXTURE_PATH.is_file(), (
        f"missing {_FIXTURE_PATH.as_posix()}; write GQ-01..GQ-10 hand constants"
    )


def test_meta_declares_hand_calculated_origin_and_fixed_clock() -> None:
    doc = _load_fixture()
    meta = doc.get("meta")
    assert isinstance(meta, dict), "root.meta required"
    assert meta.get("origin") == "hand_calculated", (
        "expected values must be hand-calculated constants, not adapter-generated"
    )
    assert meta.get("business_timezone") == "Asia/Shanghai"
    clock = meta.get("reference_clock_utc")
    assert isinstance(clock, str) and clock.endswith("Z"), (
        "reference_clock_utc must be fixed RFC3339 UTC ending with Z"
    )
    assert "today" not in clock.lower()
    assert meta.get("dataset_id") == "sales_inventory_daily"


def test_queries_cover_gq_01_through_gq_10_exactly() -> None:
    queries = _queries(_load_fixture())
    ids = sorted(queries.keys())
    assert ids == sorted(_REQUIRED_IDS), (
        f"expected exact GQ-01..GQ-10, got {ids}"
    )


def test_each_gq_has_capability_request_and_expected_shape() -> None:
    queries = _queries(_load_fixture())
    for gq_id in _REQUIRED_IDS:
        entry = queries[gq_id]
        assert isinstance(entry, dict), f"{gq_id} must be a mapping"
        assert entry.get("capability") == _CAPABILITY_BY_ID[gq_id], (
            f"{gq_id} capability mismatch"
        )
        request = entry.get("request")
        expected = entry.get("expected")
        assert isinstance(request, dict), f"{gq_id}.request required"
        assert isinstance(expected, dict), f"{gq_id}.expected required"
        assert set(request.keys()) <= _REQUEST_KEYS, (
            f"{gq_id}.request has unknown keys: {set(request) - _REQUEST_KEYS}"
        )
        assert _REQUEST_KEYS <= set(request.keys()), (
            f"{gq_id}.request missing keys: {_REQUEST_KEYS - set(request)}"
        )
        assert _EXPECTED_KEYS <= set(expected.keys()), (
            f"{gq_id}.expected missing keys: {_EXPECTED_KEYS - set(expected)}"
        )
        assert request.get("dataset_id") == "sales_inventory_daily"
        for banned in _FORBIDDEN_REQUEST_KEYS:
            assert banned not in request, f"{gq_id} must not include {banned}"


def test_expected_rows_are_hand_constants_not_live_computed() -> None:
    """Expected block must be literal constants (list/tuple), not generator hooks."""
    queries = _queries(_load_fixture())
    for gq_id, entry in queries.items():
        expected = entry["expected"]
        assert "computed_by" not in expected
        assert "generator" not in expected
        assert "sql" not in expected
        rows = expected["rows"]
        assert isinstance(rows, list), f"{gq_id}.expected.rows must be a list"
        columns = expected["columns"]
        assert isinstance(columns, list) and all(
            isinstance(c, str) for c in columns
        ), f"{gq_id}.expected.columns must be list[str]"
        row_count = expected["row_count"]
        assert isinstance(row_count, int) and row_count >= 0
        assert row_count == len(rows), (
            f"{gq_id}: row_count {row_count} != len(rows) {len(rows)}"
        )
        for row in rows:
            assert isinstance(row, list), f"{gq_id} row must be a list"
            assert len(row) == len(columns), (
                f"{gq_id} row width must match columns"
            )


def test_gq09_empty_and_gq10_truncated_semantics() -> None:
    queries = _queries(_load_fixture())
    gq09 = queries["GQ-09"]["expected"]
    assert gq09["result_status"] == "EMPTY"
    assert gq09["rows"] == []
    assert gq09["row_count"] == 0
    assert gq09["truncated"] is False
    source09 = gq09["source"]
    assert isinstance(source09, dict)
    assert source09.get("dataset_id") == "sales_inventory_daily"

    gq10 = queries["GQ-10"]["expected"]
    assert gq10["result_status"] in ("NON_EMPTY", "EMPTY")
    assert gq10["truncated"] is True
    assert isinstance(gq10["row_count"], int) and gq10["row_count"] >= 1
    assert len(gq10["rows"]) == gq10["row_count"]


def test_gq05_week_window_uses_fixed_clock_not_runtime_today() -> None:
    """PRD replenishment demo week must be absolute dates from reference clock."""
    doc = _load_fixture()
    meta = doc["meta"]
    gq05 = _queries(doc)["GQ-05"]
    request = gq05["request"]
    filters = request.get("filters")
    assert isinstance(filters, list) and filters, "GQ-05 needs date window filters"
    blob = yaml.safe_dump(gq05, allow_unicode=True)
    assert "today" not in blob.lower()
    assert meta["reference_clock_utc"] not in ("", None)


def test_number_like_expected_cells_are_decimal_strings() -> None:
    """SPEC §11.3: DECIMAL outbound as decimal strings in golden expectations."""
    queries = _queries(_load_fixture())
    # GQ-06 category sales agg is the Decimal precision case.
    gq06 = queries["GQ-06"]
    columns = gq06["expected"]["columns"]
    rows = gq06["expected"]["rows"]
    assert rows, "GQ-06 must include at least one hand-calculated aggregate row"
    # Any column whose name suggests money/sales must be str decimals in cells.
    money_idxs = [
        i
        for i, name in enumerate(columns)
        if "sales" in name.lower() or "gross" in name.lower() or "avg" in name.lower()
    ]
    assert money_idxs, "GQ-06 expected columns must include a sales/agg numeric alias"
    for row in rows:
        for i in money_idxs:
            cell = row[i]
            assert isinstance(cell, str), (
                f"GQ-06 money cell must be decimal string, got {type(cell).__name__}"
            )
            assert cell != "", "decimal string must be non-empty"


def test_fixture_does_not_import_or_call_query_port() -> None:
    """Contract: golden constants are static; no production algorithm hooks."""
    text = _FIXTURE_PATH.read_text(encoding="utf-8")
    for banned in (
        "QueryPort",
        "query_service",
        "ExecuteReadQuery",
        "adapters.outbound.mysql",
        "generate_expected",
    ):
        assert banned not in text, f"forbidden production hook in fixture: {banned}"

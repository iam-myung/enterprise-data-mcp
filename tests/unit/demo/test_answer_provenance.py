"""RED: Successful demo answers must show dataset_id, query time, and row_count (API §10)."""

from __future__ import annotations

from typing import Any, Mapping


def _agent_mod() -> Any:
    import enterprise_data_mcp_demo.agent as agent

    return agent


def _fixed_clock() -> Any:
    from enterprise_data_mcp_demo.clock import FixedClock

    return FixedClock(now_utc="2026-09-14T04:00:00Z")


class _ToolThenDoneModel:
    def __init__(self) -> None:
        self._n = 0

    def complete(self, *, user_message: str, catalog_text: str) -> Mapping[str, object]:
        self._n += 1
        if self._n == 1:
            return {
                "kind": "tool",
                "name": "query_data",
                "arguments": {
                    "dataset_id": "sales_inventory_daily",
                    "projection": ["product_name", "units_sold"],
                    "filters": [],
                    "aggregations": [],
                    "group_by": [],
                    "order_by": [],
                    "limit": 5,
                },
            }
        return {"kind": "final", "text": "销量最高的是商品 A。"}


class _OkMcp:
    def call_query_data(self, args: Mapping[str, object]) -> Mapping[str, object]:
        assert args["dataset_id"] == "sales_inventory_daily"
        return {
            "success": True,
            "data": {
                "result_status": "NON_EMPTY",
                "columns": ["product_name", "units_sold"],
                "rows": [["A", 10], ["B", 7]],
                "row_count": 2,
                "truncated": False,
                "source": {"dataset_id": "sales_inventory_daily"},
            },
            "error": None,
            "meta": {
                "trace_id": "t-ok",
                "timestamp_utc": "2026-09-14T04:00:01Z",
                "operation": "query_data",
                "duration_ms": 12,
            },
        }


def test_successful_answer_includes_provenance_fields() -> None:
    agent_mod = _agent_mod()
    demo = agent_mod.DemoAgent(
        model=_ToolThenDoneModel(),
        mcp=_OkMcp(),
        clock=_fixed_clock(),
    )
    answer = demo.handle("销量最高的商品是什么？")
    assert answer.tool_called is True
    assert answer.tool_succeeded is True
    assert answer.dataset_id == "sales_inventory_daily"
    assert answer.row_count == 2
    assert answer.queried_at_utc  # non-empty ISO/UTC timestamp
    text = answer.text
    assert "sales_inventory_daily" in text
    assert "2" in text
    assert answer.queried_at_utc in text or "2026-09-14" in text

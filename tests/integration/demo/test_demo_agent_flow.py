"""RED: Demo agent flow with FakeModel + Fake MCP (integration, no real LLM).

Covers: tool-arg validation before call, provenance on success, gate on skip.
"""

from __future__ import annotations

from typing import Any, Mapping


def _build_agent(*, model: Any, mcp: Any) -> Any:
    from enterprise_data_mcp_demo.agent import DemoAgent
    from enterprise_data_mcp_demo.clock import FixedClock

    return DemoAgent(model=model, mcp=mcp, clock=FixedClock(now_utc="2026-09-14T04:00:00Z"))


class _InvalidArgsModel:
    def complete(self, *, user_message: str, catalog_text: str) -> Mapping[str, object]:
        return {
            "kind": "tool",
            "name": "query_data",
            "arguments": {
                "dataset_id": "sales_inventory_daily",
                "projection": ["product_name"],
                "aggregations": [
                    {"function": "SUM", "field_id": "units_sold", "alias": "total"}
                ],
                "limit": 10,
            },
        }


class _RecordingMcp:
    def __init__(self) -> None:
        self.calls: list[Mapping[str, object]] = []

    def call_query_data(self, args: Mapping[str, object]) -> Mapping[str, object]:
        self.calls.append(dict(args))
        return {
            "success": True,
            "data": {
                "result_status": "NON_EMPTY",
                "columns": ["product_name"],
                "rows": [["X"]],
                "row_count": 1,
                "truncated": False,
                "source": {"dataset_id": "sales_inventory_daily"},
            },
            "error": None,
            "meta": {
                "trace_id": "t",
                "timestamp_utc": "2026-09-14T04:00:00Z",
                "operation": "query_data",
                "duration_ms": 1,
            },
        }


def test_invalid_tool_args_never_reach_mcp() -> None:
    mcp = _RecordingMcp()
    agent = _build_agent(model=_InvalidArgsModel(), mcp=mcp)
    answer = agent.handle("坏参数查询")
    assert mcp.calls == []
    assert answer.tool_succeeded is False
    text = answer.text.lower()
    assert any(
        m in text for m in ("校验", "非法", "无效", "validation", "invalid")
    ), f"expected validation message, got: {answer.text!r}"


class _HappyModel:
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
                    "projection": ["product_name"],
                    "filters": [],
                    "aggregations": [],
                    "group_by": [],
                    "order_by": [],
                    "limit": 5,
                },
            }
        return {"kind": "final", "text": "结果已就绪。"}


def test_happy_path_calls_mcp_and_returns_provenance() -> None:
    mcp = _RecordingMcp()
    agent = _build_agent(model=_HappyModel(), mcp=mcp)
    answer = agent.handle("列出商品")
    assert len(mcp.calls) == 1
    assert mcp.calls[0]["dataset_id"] == "sales_inventory_daily"
    assert answer.tool_called is True
    assert answer.tool_succeeded is True
    assert answer.dataset_id == "sales_inventory_daily"
    assert answer.row_count == 1
    assert "sales_inventory_daily" in answer.text

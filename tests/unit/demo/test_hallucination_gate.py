"""RED: Hallucination gate — no deterministic enterprise facts without successful query_data.

SPEC §14.2 / API §10.
"""

from __future__ import annotations

from typing import Any, Mapping


def _agent_mod() -> Any:
    import enterprise_data_mcp_demo.agent as agent

    return agent


def _fixed_clock() -> Any:
    from enterprise_data_mcp_demo.clock import FixedClock

    return FixedClock(now_utc="2026-09-14T04:00:00Z")


class _SilentModel:
    """Model that answers with fabricated numbers and never requests a tool."""

    def complete(self, *, user_message: str, catalog_text: str) -> Mapping[str, object]:
        return {
            "kind": "final",
            "text": "本周销量是 99999 件，库存 88888。",
        }


class _NoCallMcp:
    def call_query_data(self, args: Mapping[str, object]) -> Mapping[str, object]:
        raise AssertionError("query_data must not be called in this scenario")


def test_refuse_deterministic_data_when_tool_not_called() -> None:
    agent_mod = _agent_mod()
    demo = agent_mod.DemoAgent(
        model=_SilentModel(),
        mcp=_NoCallMcp(),
        clock=_fixed_clock(),
    )
    answer = demo.handle("本周销量多少？")
    assert answer.tool_called is False
    assert answer.tool_succeeded is False
    text = answer.text.lower()
    # Must not present fabricated magnitudes as facts
    assert "99999" not in answer.text
    assert "88888" not in answer.text
    assert any(
        marker in text
        for marker in ("未调用", "无法", "不能", "没有查询", "未能", "no query", "not call")
    ), f"expected explicit no-tool explanation, got: {answer.text!r}"


class _FailingToolModel:
    def complete(self, *, user_message: str, catalog_text: str) -> Mapping[str, object]:
        return {
            "kind": "tool",
            "name": "query_data",
            "arguments": {
                "dataset_id": "sales_inventory_daily",
                "projection": ["product_name"],
                "limit": 10,
            },
        }


class _FailingMcp:
    def call_query_data(self, args: Mapping[str, object]) -> Mapping[str, object]:
        return {
            "success": False,
            "data": None,
            "error": {
                "code": "DATA_SOURCE_UNAVAILABLE",
                "message": "data source unavailable",
                "context": {"dataset_id": "sales_inventory_daily"},
            },
            "meta": {
                "trace_id": "t-fail",
                "timestamp_utc": "2026-09-14T04:00:00Z",
                "operation": "query_data",
                "duration_ms": 1,
            },
        }


def test_refuse_deterministic_data_when_tool_fails() -> None:
    agent_mod = _agent_mod()
    demo = agent_mod.DemoAgent(
        model=_FailingToolModel(),
        mcp=_FailingMcp(),
        clock=_fixed_clock(),
    )
    answer = demo.handle("查一下销量")
    assert answer.tool_called is True
    assert answer.tool_succeeded is False
    # Must surface safe failure, not invent row facts
    assert "99999" not in answer.text
    assert answer.row_count is None
    text = answer.text.lower()
    assert any(
        marker in text
        for marker in ("失败", "不可用", "错误", "fail", "unavailable", "error")
    ), f"expected failure explanation, got: {answer.text!r}"

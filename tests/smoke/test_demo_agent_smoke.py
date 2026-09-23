"""Step 13 SMOKE: Demo Agent + real MCP Host (SPEC §18.4 / Agent Demo Gate).

真实 stdio MCP · 确定性 FakeModel · 来源字段 · 未调用不编造 · 进程清理.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Mapping

import anyio
from fastmcp import Client
from fastmcp.client.transports import StdioTransport

from enterprise_data_mcp_demo.agent import DemoAgent
from enterprise_data_mcp_demo.clock import FixedClock

PROJECT_ROOT = Path(__file__).resolve().parents[2]

_TOOL_NAME = "query_data"
_DATASET = "sales_inventory_daily"
_CALLER_ID = "demo-agent-smoke-client"
_POLICY_PROFILE = "demo_readonly"
_PRIMARY_PROTOCOL = "2026-07-28"

_HOST_ENV = {
    "MCP_CALLER_ID": _CALLER_ID,
    "MCP_POLICY_PROFILE": _POLICY_PROFILE,
    "MCP_TRANSPORT": "stdio",
    "ENTERPRISE_DATA_MCP_STDIO_DEMO": "1",
    "PYTHONUNBUFFERED": "1",
}


def _host_env() -> dict[str, str]:
    return {**os.environ, **_HOST_ENV}


def _envelope_from_call(call: Any) -> dict[str, Any]:
    if getattr(call, "structured_content", None) is not None:
        payload = call.structured_content
    else:
        data = getattr(call, "data", None)
        if isinstance(data, dict):
            payload = data
        else:
            content = getattr(call, "content", None) or []
            payload = json.loads(content[0].text)
    assert isinstance(payload, dict)
    return payload


class _LiveStdioMcp:
    """One real stdio Host subprocess per query_data call (SPEC §18.4)."""

    def call_query_data(self, args: Mapping[str, object]) -> Mapping[str, object]:
        async def _run() -> dict[str, Any]:
            transport = StdioTransport(
                command=sys.executable,
                args=["-m", "enterprise_data_mcp.hosts.stdio"],
                cwd=str(PROJECT_ROOT),
                env=_host_env(),
            )
            async with Client(transport) as client:
                assert client.protocol_version == _PRIMARY_PROTOCOL
                tools = await client.list_tools()
                names = {t.name for t in tools}
                assert _TOOL_NAME in names
                assert "execute_sql" not in names
                call = await client.call_tool(
                    _TOOL_NAME,
                    {"request": dict(args)},
                )
                return _envelope_from_call(call)

        return anyio.run(_run)


class _QueryThenNarrateModel:
    def __init__(self) -> None:
        self._n = 0

    def complete(self, *, user_message: str, catalog_text: str) -> Mapping[str, object]:
        self._n += 1
        if self._n == 1:
            return {
                "kind": "tool",
                "name": "query_data",
                "arguments": {
                    "dataset_id": _DATASET,
                    "projection": ["product_name"],
                    "filters": [],
                    "aggregations": [],
                    "group_by": [],
                    "order_by": [],
                    "limit": 10,
                },
            }
        return {"kind": "final", "text": "查询完成（确定性模型）。"}


class _FabricatingModel:
    def complete(self, *, user_message: str, catalog_text: str) -> Mapping[str, object]:
        return {
            "kind": "final",
            "text": "本周销量是 99999 件，库存 88888。",
        }


class _MustNotCallMcp:
    def call_query_data(self, args: Mapping[str, object]) -> Mapping[str, object]:
        raise AssertionError("MCP must not be called when model skips tools")


def test_demo_agent_real_mcp_query_with_provenance() -> None:
    """真实 MCP call_tool + DemoAgent 来源字段（dataset / 时间 / 行数）。"""
    agent = DemoAgent(
        model=_QueryThenNarrateModel(),
        mcp=_LiveStdioMcp(),
        clock=FixedClock(now_utc="2026-09-14T04:00:00Z"),
    )
    answer = agent.handle("列出商品名称")

    assert answer.tool_called is True
    assert answer.tool_succeeded is True
    assert answer.dataset_id == _DATASET
    assert answer.row_count == 0  # demo FakeQueryPort returns EMPTY
    assert answer.queried_at_utc
    assert _DATASET in answer.text
    assert "0" in answer.text
    assert answer.queried_at_utc in answer.text or "2026-09-14" in answer.text
    assert "99999" not in answer.text


def test_demo_agent_hallucination_gate_and_host_cleanup() -> None:
    """未调用工具不编造；另启真实 Host 并确认 teardown 无悬挂。"""
    agent = DemoAgent(
        model=_FabricatingModel(),
        mcp=_MustNotCallMcp(),
        clock=FixedClock(now_utc="2026-09-14T04:00:00Z"),
    )
    answer = agent.handle("本周销量多少？")
    assert answer.tool_called is False
    assert answer.tool_succeeded is False
    assert "99999" not in answer.text
    assert "88888" not in answer.text
    text = answer.text.lower()
    assert any(
        m in text for m in ("未调用", "无法", "不能", "没有查询", "未能")
    ), answer.text

    # Resource cleanup: real host starts and exits cleanly after terminate.
    proc = subprocess.Popen(
        [sys.executable, "-u", "-m", "enterprise_data_mcp.hosts.stdio"],
        cwd=str(PROJECT_ROOT),
        env=_host_env(),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        time.sleep(0.4)
        assert proc.poll() is None, "stdio host exited before smoke probe"
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=2)
    assert proc.poll() is not None, "stdio host still alive after teardown"

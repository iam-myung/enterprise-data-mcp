"""QA-04 / AC-09: Agent E2E — 10 NL tasks (≥90%) + live MySQL MCP; real-model gate.

Deterministic model may drive tool selection for the 10-task suite.
At least one task MUST use OpenAICompatModel + live MCP + live MySQL.
"""

from __future__ import annotations

import os
import re
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from enterprise_data_mcp_demo.agent import DemoAgent, DemoAnswer
from enterprise_data_mcp_demo.clock import FixedClock
from enterprise_data_mcp_demo.mcp_tooling import StdioMcpClient
from enterprise_data_mcp_demo.model_port import DeterministicQueryModel
from scripts.compose_e2e import docker_bin, ensure_mysql_up, mysql_port_open

PROJECT_ROOT = Path(__file__).resolve().parents[2]

_DATASET = "sales_inventory_daily"

# 10 natural-language business query tasks (PRD AC-09 / §9 metrics).
_NL_TASKS: tuple[str, ...] = (
    "列出商品名称",
    "查询今日可售商品清单",
    "看看销售库存日报里有哪些产品",
    "给我商品名称列表，最多10条",
    "从销售库存数据里取产品名",
    "展示 sales_inventory_daily 的商品名",
    "有哪些商品在库存日报中？",
    "拉取只读商品名称明细",
    "查询授权数据集中的产品名称",
    "请返回商品名称字段的查询结果",
)

_PROVENANCE_MARKERS = ("数据集", "查询时间", "返回条数")
_BUSINESS_NUMBER_RE = re.compile(r"(?<![A-Fa-f0-9])\b\d{3,}\b")


def _mysql_stdio_env() -> dict[str, str]:
    return {
        **os.environ,
        "MCP_CONTAINER": "mysql",
        "MCP_TRANSPORT": "stdio",
        "MCP_CALLER_ID": "qa04-agent-client",
        "MCP_POLICY_PROFILE": "demo_readonly",
        "MYSQL_HOST": os.environ.get("MYSQL_HOST", "127.0.0.1"),
        "MYSQL_PORT": os.environ.get("MYSQL_PORT", "3307"),
        "MYSQL_USER": os.environ.get("MYSQL_USER", "edmcp_ro"),
        "MYSQL_PASSWORD": os.environ.get("MYSQL_PASSWORD", "demoro"),
        "MYSQL_DATABASE": os.environ.get("MYSQL_DATABASE", "edmcp_demo"),
        "PYTHONUNBUFFERED": "1",
    }


def _task_ok(answer: DemoAnswer, *, message: str) -> bool:
    _ = message
    if not answer.tool_called or not answer.tool_succeeded:
        return False
    if answer.dataset_id != _DATASET:
        return False
    if answer.row_count is None or int(answer.row_count) <= 0:
        return False
    if not answer.queried_at_utc:
        return False
    # Fake demo empty path / FakeClock sentinel used by demo container
    if answer.queried_at_utc == "2026-09-14T00:00:00Z":
        return False
    text = answer.text
    if not all(m in text for m in _PROVENANCE_MARKERS):
        return False
    if _DATASET not in text:
        return False
    if str(answer.row_count) not in text:
        return False
    return True


@pytest.fixture(scope="module")
def live_mysql() -> Iterator[None]:
    if docker_bin() is None:
        pytest.fail("QA-04 BLOCK: docker binary not found — live MySQL required")
    if mysql_port_open():
        yield
        return
    try:
        ensure_mysql_up(timeout_s=120.0)
    except Exception as exc:  # noqa: BLE001 — surface env BLOCK clearly
        pytest.fail(
            "QA-04 BLOCK: cannot start compose MySQL "
            f"(Docker Desktop/WSL unhealthy?): {exc}"
        )
    deadline = time.monotonic() + 90.0
    while time.monotonic() < deadline and not mysql_port_open():
        time.sleep(0.5)
    if not mysql_port_open():
        pytest.fail("QA-04 BLOCK: MySQL 127.0.0.1:3307 not reachable after compose up")
    time.sleep(2.0)
    yield


@pytest.mark.timeout(300)
def test_ac09_ten_nl_tasks_completion_rate_ge_90_live_mysql(live_mysql: None) -> None:
    """10 NL tasks via DeterministicQueryModel + real stdio MCP + live MySQL."""
    mcp = StdioMcpClient(environ=_mysql_stdio_env())
    clock = FixedClock(now_utc="2026-09-14T16:00:00Z")
    results: list[tuple[str, bool, str]] = []
    for message in _NL_TASKS:
        agent = DemoAgent(
            model=DeterministicQueryModel(),
            mcp=mcp,
            clock=clock,
        )
        answer = agent.handle(message)
        ok = _task_ok(answer, message=message)
        results.append((message, ok, answer.text[:200]))
    passed = sum(1 for _, ok, _ in results if ok)
    rate = passed / len(_NL_TASKS)
    print(
        "QA04_TEN_TASK_SUMMARY",
        {"passed": passed, "total": len(_NL_TASKS), "rate": rate, "results": results},
    )
    assert rate >= 0.90, f"task completion rate {rate:.0%} < 90%: {results!r}"


@pytest.mark.timeout(60)
def test_ac09_hallucination_gate_no_business_numbers_without_tool() -> None:
    class _Fabricating:
        def complete(self, *, user_message: str, catalog_text: str) -> dict[str, object]:
            return {"kind": "final", "text": "本周销量是 99999 件，库存 88888。"}

    class _NoMcp:
        def call_query_data(self, args: object) -> dict[str, object]:
            raise AssertionError("must not call MCP")

    agent = DemoAgent(
        model=_Fabricating(),
        mcp=_NoMcp(),
        clock=FixedClock(now_utc="2026-09-14T16:00:00Z"),
    )
    answer = agent.handle("本周销量多少？")
    assert answer.tool_called is False
    assert "99999" not in answer.text
    assert "88888" not in answer.text


@pytest.mark.timeout(180)
def test_ac09_at_least_one_real_model_live_mcp_mysql(live_mysql: None) -> None:
    """Hard gate: real model + real MCP + real MySQL (cannot substitute FakeModel)."""
    api_key = (os.environ.get("MODEL_API_KEY") or "").strip()
    base_url = (os.environ.get("MODEL_BASE_URL") or "").strip()
    model_name = (os.environ.get("MODEL_NAME") or "").strip()
    if not api_key or not base_url or not model_name:
        pytest.fail(
            "QA-04 BLOCK: real-model acceptance requires MODEL_API_KEY, "
            "MODEL_BASE_URL, and MODEL_NAME in the environment. "
            "DeterministicQueryModel must not substitute for this gate."
        )

    from enterprise_data_mcp_demo.model_port import OpenAICompatModel

    model = OpenAICompatModel(
        api_key=api_key,
        base_url=base_url,
        model_name=model_name,
    )
    assert type(model).__name__ == "OpenAICompatModel"
    mcp = StdioMcpClient(environ=_mysql_stdio_env())
    agent = DemoAgent(
        model=model,
        mcp=mcp,
        clock=FixedClock(now_utc="2026-09-14T16:00:00Z"),
    )
    answer = agent.handle("列出商品名称")
    print(
        "QA04_REAL_MODEL_EVIDENCE",
        {
            "model_type": type(model).__name__,
            "tool_called": answer.tool_called,
            "tool_succeeded": answer.tool_succeeded,
            "dataset_id": answer.dataset_id,
            "row_count": answer.row_count,
            "queried_at_utc": answer.queried_at_utc,
            "text": answer.text[:400],
        },
    )
    assert _task_ok(answer, message="列出商品名称"), answer.text
    assert answer.row_count and int(answer.row_count) > 0

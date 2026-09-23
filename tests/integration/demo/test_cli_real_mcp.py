"""BUG-03-RED: CLI path must complete NL → public MCP Host → provenance (API §10).

Approved (BUG-03-PLAN): deterministic tool model + live Host (MCP_CONTAINER=mysql).
No production changes in this Step.
"""

from __future__ import annotations

import re

import pytest


@pytest.mark.timeout(120)
def test_cli_main_deterministic_model_live_mcp_prints_provenance(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """CLI main must call real MCP and print dataset / time / positive row_count."""
    from scripts.compose_e2e import docker_bin, ensure_mysql_up

    if docker_bin() is None:
        pytest.fail("docker required for live MySQL Host (BUG-03-RED)")

    ensure_mysql_up(timeout_s=120.0)

    monkeypatch.setenv("DEMO_MODEL", "deterministic")
    monkeypatch.setenv("DEMO_MCP_TRANSPORT", "stdio")
    monkeypatch.setenv("MCP_CONTAINER", "mysql")
    monkeypatch.setenv("MCP_CALLER_ID", "bug03-red-cli")
    monkeypatch.setenv("MCP_POLICY_PROFILE", "demo_readonly")
    monkeypatch.setenv("MCP_TRANSPORT", "stdio")
    monkeypatch.setenv("MYSQL_HOST", "127.0.0.1")
    monkeypatch.setenv("MYSQL_PORT", "3307")
    monkeypatch.setenv("MYSQL_USER", "edmcp_ro")
    monkeypatch.setenv("MYSQL_PASSWORD", "demoro")
    monkeypatch.setenv("MYSQL_DATABASE", "edmcp_demo")

    from enterprise_data_mcp_demo.cli import main

    code = main(["列出商品名称"])
    out = capsys.readouterr().out

    assert code == 0, f"CLI exit {code}, out={out!r}"
    assert "NullMcpClient" not in out
    assert "未调用查询工具" not in out, (
        "Echo/skip-tool path is not success evidence; need real query_data"
    )
    assert "数据集：" in out or "sales_inventory_daily" in out, out
    assert "返回条数：" in out, out
    match = re.search(r"返回条数：(\d+)", out)
    assert match is not None, f"missing row_count provenance: {out!r}"
    assert int(match.group(1)) > 0, (
        f"expected live MySQL row_count>0, got {match.group(1)} (Fake EMPTY not allowed)"
    )

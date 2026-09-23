"""BUG-01-RED: three Host main() entrypoints must honor MCP_CONTAINER=mysql.

Approved (BUG-01-PLAN). No production changes in this Step.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest


@pytest.mark.parametrize(
    "module_path",
    [
        "enterprise_data_mcp.hosts.stdio",
        "enterprise_data_mcp.hosts.streamable_http",
        "enterprise_data_mcp.hosts.sse",
    ],
)
def test_host_main_uses_mysql_container_when_configured(
    monkeypatch: pytest.MonkeyPatch,
    module_path: str,
) -> None:
    import importlib

    host_mod = importlib.import_module(module_path)

    counts = {"demo": 0, "mysql": 0}

    def _demo(_settings: Any) -> Any:
        counts["demo"] += 1
        return MagicMock(name="demo-container")

    def _mysql(_settings: Any) -> Any:
        counts["mysql"] += 1
        return MagicMock(name="mysql-container")

    from enterprise_data_mcp.bootstrap import container as container_mod

    monkeypatch.setattr(container_mod, "build_demo_container", _demo)
    monkeypatch.setattr(container_mod, "build_mysql_container", _mysql)
    if hasattr(host_mod, "build_demo_container"):
        monkeypatch.setattr(host_mod, "build_demo_container", _demo)
    if hasattr(host_mod, "build_mysql_container"):
        monkeypatch.setattr(host_mod, "build_mysql_container", _mysql)

    if module_path.endswith("stdio"):
        monkeypatch.setattr(
            host_mod,
            "build_stdio_server",
            lambda **kwargs: MagicMock(run=MagicMock()),
        )
        monkeypatch.setenv("MCP_TRANSPORT", "stdio")
        monkeypatch.setenv("MCP_CALLER_ID", "bug01-stdio")
        monkeypatch.setenv("MCP_POLICY_PROFILE", "demo_readonly")
    elif module_path.endswith("streamable_http"):
        monkeypatch.setattr(
            host_mod, "build_streamable_http_app", lambda **kwargs: MagicMock()
        )
        monkeypatch.setattr(host_mod.uvicorn, "run", MagicMock())
        monkeypatch.setenv("MCP_TRANSPORT", "streamable_http")
        monkeypatch.setenv("MCP_HOST", "127.0.0.1")
        monkeypatch.setenv("MCP_PORT", "18000")
        monkeypatch.setenv("MCP_ALLOWED_ORIGINS", "http://127.0.0.1")
        monkeypatch.setenv("MCP_CALLER_ID", "bug01-http")
        monkeypatch.setenv("MCP_POLICY_PROFILE", "demo_readonly")
    else:
        monkeypatch.setattr(host_mod, "build_sse_app", lambda **kwargs: MagicMock())
        monkeypatch.setattr(host_mod.uvicorn, "run", MagicMock())
        monkeypatch.setenv("MCP_TRANSPORT", "sse")
        monkeypatch.setenv("MCP_HOST", "127.0.0.1")
        monkeypatch.setenv("MCP_PORT", "18001")
        monkeypatch.setenv("MCP_ALLOWED_ORIGINS", "http://127.0.0.1")
        monkeypatch.setenv("MCP_CALLER_ID", "bug01-sse")
        monkeypatch.setenv("MCP_POLICY_PROFILE", "demo_readonly")

    monkeypatch.setenv("MCP_CONTAINER", "mysql")
    host_mod.main()

    assert counts["mysql"] >= 1, (
        f"{module_path}.main() must use build_mysql_container when MCP_CONTAINER=mysql"
    )
    assert counts["demo"] == 0

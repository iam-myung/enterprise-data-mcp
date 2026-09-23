"""BUG-03-RED: Demo CLI must not default to EchoModel + NullMcpClient.

Approved (BUG-03-PLAN): build_runtime factory; real MCP + deterministic/real model.
No production changes in this Step.
"""

from __future__ import annotations

import pytest


def test_cli_build_runtime_factory_exists() -> None:
    from enterprise_data_mcp_demo import cli

    assert hasattr(cli, "build_runtime"), (
        "cli.build_runtime(environ) must assemble model+mcp for DemoAgent"
    )
    assert callable(cli.build_runtime)


def test_cli_build_runtime_rejects_null_mcp_and_echo_defaults() -> None:
    from enterprise_data_mcp_demo import cli
    from enterprise_data_mcp_demo.mcp_tooling import NullMcpClient
    from enterprise_data_mcp_demo.model_port import EchoModel

    runtime = cli.build_runtime(
        {
            "DEMO_MODEL": "deterministic",
            "DEMO_MCP_TRANSPORT": "stdio",
            "MCP_CONTAINER": "mysql",
            "MCP_CALLER_ID": "bug03-red-cli",
            "MCP_POLICY_PROFILE": "demo_readonly",
            "MCP_TRANSPORT": "stdio",
        }
    )
    model = runtime["model"] if isinstance(runtime, dict) else runtime.model
    mcp = runtime["mcp"] if isinstance(runtime, dict) else runtime.mcp

    assert not isinstance(model, EchoModel), (
        "CLI default must not use EchoModel (never selects query_data)"
    )
    assert not isinstance(mcp, NullMcpClient), (
        "CLI default must not use NullMcpClient (cannot complete NL→MCP→data)"
    )


def test_cli_main_source_must_not_hardcode_echo_and_null() -> None:
    """Guard: production main() path must not construct EchoModel()/NullMcpClient()."""
    from pathlib import Path

    path = Path(__file__).resolve().parents[3] / "src" / "enterprise_data_mcp_demo" / "cli.py"
    src = path.read_text(encoding="utf-8")
    assert "EchoModel()" not in src, "cli.py must not hardcode EchoModel()"
    assert "NullMcpClient()" not in src, "cli.py must not hardcode NullMcpClient()"

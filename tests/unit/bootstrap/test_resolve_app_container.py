"""BUG-01-RED: Hosts must resolve demo vs mysql container via MCP_CONTAINER.

Approved (BUG-01-PLAN): resolve_app_container + three main() entrypoints.
No production changes in this Step.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest


def test_resolve_app_container_module_export_exists() -> None:
    from enterprise_data_mcp.bootstrap.container import resolve_app_container

    assert callable(resolve_app_container)


def test_resolve_app_container_selects_mysql_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from enterprise_data_mcp.bootstrap import container as container_mod
    from enterprise_data_mcp.bootstrap.settings import load_stdio_settings
    from enterprise_data_mcp.domain.errors import TransportKind
    from enterprise_data_mcp.domain.models import CallerContext

    settings = load_stdio_settings(
        {
            "MCP_CALLER_ID": "bug01-red",
            "MCP_POLICY_PROFILE": "demo_readonly",
            "MCP_TRANSPORT": "stdio",
        }
    )
    demo_calls: list[Any] = []
    mysql_calls: list[Any] = []

    def _fake_demo(s: Any) -> Any:
        demo_calls.append(s)
        return MagicMock(
            name="demo",
            caller=CallerContext(
                caller_id="bug01-red",
                policy_profile="demo_readonly",
                transport=TransportKind.STDIO,
            ),
        )

    def _fake_mysql(s: Any) -> Any:
        mysql_calls.append(s)
        return MagicMock(
            name="mysql",
            caller=CallerContext(
                caller_id="bug01-red",
                policy_profile="demo_readonly",
                transport=TransportKind.STDIO,
            ),
        )

    monkeypatch.setattr(container_mod, "build_demo_container", _fake_demo)
    monkeypatch.setattr(container_mod, "build_mysql_container", _fake_mysql)

    resolved = container_mod.resolve_app_container(
        settings, {"MCP_CONTAINER": "mysql"}
    )
    assert len(mysql_calls) == 1, "MCP_CONTAINER=mysql must call build_mysql_container"
    assert not demo_calls
    assert resolved is not None


def test_resolve_app_container_defaults_to_demo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from enterprise_data_mcp.bootstrap import container as container_mod
    from enterprise_data_mcp.bootstrap.settings import load_stdio_settings
    from enterprise_data_mcp.domain.errors import TransportKind
    from enterprise_data_mcp.domain.models import CallerContext

    settings = load_stdio_settings(
        {
            "MCP_CALLER_ID": "bug01-red",
            "MCP_POLICY_PROFILE": "demo_readonly",
            "MCP_TRANSPORT": "stdio",
        }
    )
    demo_calls: list[Any] = []
    mysql_calls: list[Any] = []

    monkeypatch.setattr(
        container_mod,
        "build_demo_container",
        lambda s: demo_calls.append(s) or MagicMock(
            caller=CallerContext(
                caller_id="bug01-red",
                policy_profile="demo_readonly",
                transport=TransportKind.STDIO,
            )
        ),
    )
    monkeypatch.setattr(
        container_mod,
        "build_mysql_container",
        lambda s: mysql_calls.append(s) or MagicMock(),
    )

    container_mod.resolve_app_container(settings, {})
    assert demo_calls, "default must call build_demo_container"
    assert not mysql_calls

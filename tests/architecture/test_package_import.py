"""RED: empty package skeleton must be importable (SPEC §5 / Step 1)."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

LAYER_PACKAGES: tuple[str, ...] = (
    "enterprise_data_mcp",
    "enterprise_data_mcp.domain",
    "enterprise_data_mcp.application",
    "enterprise_data_mcp.adapters",
    "enterprise_data_mcp.adapters.inbound",
    "enterprise_data_mcp.adapters.inbound.mcp",
    "enterprise_data_mcp.adapters.outbound",
    "enterprise_data_mcp.adapters.outbound.mysql",
    "enterprise_data_mcp.adapters.policy",
    "enterprise_data_mcp.adapters.audit",
    "enterprise_data_mcp.adapters.observability",
    "enterprise_data_mcp.hosts",
    "enterprise_data_mcp.bootstrap",
)

HOST_MODULES: tuple[str, ...] = (
    "enterprise_data_mcp.hosts.stdio",
    "enterprise_data_mcp.hosts.sse",
    "enterprise_data_mcp.hosts.streamable_http",
)


@pytest.mark.parametrize("module_name", LAYER_PACKAGES)
def test_layer_package_is_importable(module_name: str) -> None:
    module = importlib.import_module(module_name)
    assert module.__name__ == module_name


@pytest.mark.parametrize("module_name", HOST_MODULES)
def test_host_module_is_importable(module_name: str) -> None:
    module = importlib.import_module(module_name)
    assert module.__name__ == module_name


def test_package_exposes_typed_marker(package_root: Path) -> None:
    typed = package_root / "py.typed"
    assert typed.is_file(), "expected src/enterprise_data_mcp/py.typed for typed package"

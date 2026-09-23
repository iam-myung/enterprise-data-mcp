"""Shared fixtures for architecture and smoke tests."""

from __future__ import annotations

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
PACKAGE_ROOT = SRC_ROOT / "enterprise_data_mcp"

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


@pytest.fixture(scope="session")
def project_root() -> Path:
    return PROJECT_ROOT


@pytest.fixture(scope="session")
def src_root() -> Path:
    return SRC_ROOT


@pytest.fixture(scope="session")
def package_root() -> Path:
    return PACKAGE_ROOT

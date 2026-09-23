"""Integration fixtures for MySQL Adapter (Step 6.2).

Connection settings come from env with demo defaults (compose port 3307).
RED fails on missing adapter modules before requiring a live DB.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
import yaml

_PROJECT_ROOT = Path(__file__).resolve().parents[5]
_GOLDEN_PATH = _PROJECT_ROOT / "tests" / "fixtures" / "golden_queries.yaml"


@pytest.fixture(scope="module")
def golden_doc() -> dict[str, Any]:
    raw = yaml.safe_load(_GOLDEN_PATH.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    return raw


@pytest.fixture(scope="module")
def mysql_settings() -> dict[str, Any]:
    from scripts.compose_e2e import ensure_mysql_up, mysql_port_open

    if not mysql_port_open():
        ensure_mysql_up(timeout_s=120.0)
    return {
        "host": os.environ.get("MYSQL_HOST", "127.0.0.1"),
        "port": int(os.environ.get("MYSQL_PORT", "3307")),
        "user": os.environ.get("MYSQL_USER", "edmcp_ro"),
        "password": os.environ.get("MYSQL_PASSWORD", "demoro"),
        "database": os.environ.get("MYSQL_DATABASE", "edmcp_demo"),
        "query_timeout_ms": int(os.environ.get("MYSQL_QUERY_TIMEOUT_MS", "5000")),
        "queried_at_utc": "2026-09-13T00:00:00Z",
    }


@pytest.fixture(scope="module")
def query_adapter(mysql_settings: dict[str, Any]) -> Any:
    from enterprise_data_mcp.adapters.outbound.mysql.query_adapter import (
        MysqlQueryAdapter,
    )

    return MysqlQueryAdapter(**mysql_settings)


@pytest.fixture(scope="module")
def catalog_adapter(mysql_settings: dict[str, Any]) -> Any:
    from enterprise_data_mcp.adapters.outbound.mysql.catalog_adapter import (
        MysqlCatalogAdapter,
    )

    kwargs = {
        k: v
        for k, v in mysql_settings.items()
        if k != "queried_at_utc"
    }
    return MysqlCatalogAdapter(**kwargs)

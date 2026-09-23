"""BUG-06-RED: Compose must declare MCP HTTP/SSE services + audit volume (SPEC §15.1).

Approved (BUG-06-PLAN): services mysql + mcp-http + mcp-sse; named audit volume.
No production changes in this Step.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

_COMPOSE_PATH = Path(__file__).resolve().parents[3] / "docker" / "compose.yaml"
_REQUIRED_SERVICES = ("mysql", "mcp-http", "mcp-sse")
_AUDIT_VOLUME = "edmcp_audit"


def _load_compose() -> dict[str, Any]:
    assert _COMPOSE_PATH.is_file(), f"missing compose file: {_COMPOSE_PATH}"
    raw = yaml.safe_load(_COMPOSE_PATH.read_text(encoding="utf-8"))
    assert isinstance(raw, dict), "compose.yaml must parse to a mapping"
    return raw


def test_compose_declares_mysql_http_and_sse_services() -> None:
    compose = _load_compose()
    services = compose.get("services")
    assert isinstance(services, dict), "compose.yaml must declare services"
    missing = [name for name in _REQUIRED_SERVICES if name not in services]
    assert not missing, (
        "SPEC §15.1 requires Compose MySQL + Streamable HTTP + SSE; "
        f"missing service(s): {missing}"
    )


def test_compose_declares_named_audit_volume() -> None:
    compose = _load_compose()
    volumes = compose.get("volumes")
    assert isinstance(volumes, dict), (
        "SPEC §15.1 requires an independent audit SQLite persistent volume; "
        "compose.yaml volumes: is missing or not a mapping"
    )
    assert _AUDIT_VOLUME in volumes, (
        f"compose.yaml must declare named volume {_AUDIT_VOLUME!r} for audit SQLite"
    )


def test_mcp_http_and_sse_mount_audit_volume_and_use_mysql_container() -> None:
    compose = _load_compose()
    services = compose.get("services") or {}
    for name in ("mcp-http", "mcp-sse"):
        assert name in services, f"missing service {name!r}"
        svc = services[name]
        assert isinstance(svc, dict), f"service {name!r} must be a mapping"
        env = svc.get("environment") or {}
        if isinstance(env, list):
            env_map = {}
            for item in env:
                if isinstance(item, str) and "=" in item:
                    k, _, v = item.partition("=")
                    env_map[k] = v
            env = env_map
        assert isinstance(env, dict), f"{name} environment must be a mapping or KEY=VAL list"
        assert str(env.get("MCP_CONTAINER", "")).lower() == "mysql", (
            f"{name} must set MCP_CONTAINER=mysql for live MySQL (not demo Fake)"
        )
        mounts = svc.get("volumes") or []
        assert isinstance(mounts, list), f"{name} must declare volumes list"
        joined = "\n".join(str(m) for m in mounts)
        assert _AUDIT_VOLUME in joined, (
            f"{name} must mount named volume {_AUDIT_VOLUME!r} for AUDIT_DB_PATH"
        )
        assert "AUDIT_DB_PATH" in env, f"{name} must set AUDIT_DB_PATH on the audit volume"


@pytest.mark.timeout(30)
def test_compose_file_is_not_mysql_only_stack() -> None:
    """Guard: finishing with only mysql is explicitly forbidden by BUG-06."""
    compose = _load_compose()
    services = set((compose.get("services") or {}).keys())
    assert services != {"mysql"}, (
        "compose stack must not be MySQL-only; need mcp-http and mcp-sse"
    )

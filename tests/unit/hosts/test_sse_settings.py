"""RED: SSE Host settings (SPEC Step 12 / §12 MCP_LEGACY_*).

No production load_sse_settings until 12-GREEN.
"""

from __future__ import annotations

import pytest

from enterprise_data_mcp.domain.errors import TransportKind


def test_load_sse_settings_binds_legacy_session_limits() -> None:
    from enterprise_data_mcp.bootstrap.settings import load_sse_settings

    settings = load_sse_settings(
        {
            "MCP_TRANSPORT": "sse",
            "MCP_HOST": "127.0.0.1",
            "MCP_PORT": "8001",
            "MCP_PATH": "/sse",
            "MCP_ALLOWED_ORIGINS": "http://127.0.0.1:3000",
            "MCP_MAX_REQUEST_BODY_BYTES": "1048576",
            "MCP_MAX_INFLIGHT_REQUESTS": "32",
            "MCP_LEGACY_MAX_SESSIONS": "8",
            "MCP_LEGACY_SESSION_IDLE_TIMEOUT_SECONDS": "120",
            "MCP_CALLER_ID": "demo-sse-client",
            "MCP_POLICY_PROFILE": "demo_readonly",
        }
    )
    assert settings.host == "127.0.0.1"
    assert settings.port == 8001
    assert settings.path == "/sse"
    assert settings.transport == TransportKind.SSE
    assert settings.legacy_max_sessions == 8
    assert settings.legacy_session_idle_timeout_seconds == 120
    assert settings.allowed_origins == frozenset({"http://127.0.0.1:3000"})
    assert settings.caller_id == "demo-sse-client"


def test_load_sse_settings_allows_container_any_host() -> None:
    from enterprise_data_mcp.bootstrap.settings import load_sse_settings

    settings = load_sse_settings(
        {
            "MCP_TRANSPORT": "sse",
            "MCP_HOST": "0.0.0.0",
            "MCP_PORT": "8001",
            "MCP_PATH": "/sse",
            "MCP_ALLOWED_ORIGINS": "http://127.0.0.1:3000",
            "MCP_LEGACY_MAX_SESSIONS": "16",
            "MCP_LEGACY_SESSION_IDLE_TIMEOUT_SECONDS": "300",
            "MCP_CALLER_ID": "demo-sse-client",
            "MCP_POLICY_PROFILE": "demo_readonly",
        }
    )
    assert settings.host == "0.0.0.0"


def test_load_sse_settings_rejects_public_unicast_host() -> None:
    from enterprise_data_mcp.bootstrap.settings import load_sse_settings

    with pytest.raises(ValueError, match="0.0.0.0|loopback"):
        load_sse_settings(
            {
                "MCP_TRANSPORT": "sse",
                "MCP_HOST": "192.168.1.10",
                "MCP_PORT": "8001",
                "MCP_PATH": "/sse",
                "MCP_ALLOWED_ORIGINS": "http://127.0.0.1:3000",
                "MCP_LEGACY_MAX_SESSIONS": "16",
                "MCP_LEGACY_SESSION_IDLE_TIMEOUT_SECONDS": "300",
                "MCP_CALLER_ID": "demo-sse-client",
                "MCP_POLICY_PROFILE": "demo_readonly",
            }
        )


def test_load_sse_settings_rejects_out_of_range_session_limits() -> None:
    from enterprise_data_mcp.bootstrap.settings import load_sse_settings

    with pytest.raises(ValueError, match="session|1|64"):
        load_sse_settings(
            {
                "MCP_TRANSPORT": "sse",
                "MCP_HOST": "127.0.0.1",
                "MCP_PORT": "8001",
                "MCP_PATH": "/sse",
                "MCP_ALLOWED_ORIGINS": "http://127.0.0.1:3000",
                "MCP_LEGACY_MAX_SESSIONS": "100",
                "MCP_LEGACY_SESSION_IDLE_TIMEOUT_SECONDS": "300",
                "MCP_CALLER_ID": "demo-sse-client",
                "MCP_POLICY_PROFILE": "demo_readonly",
            }
        )

    with pytest.raises(ValueError, match="idle|timeout|30|900"):
        load_sse_settings(
            {
                "MCP_TRANSPORT": "sse",
                "MCP_HOST": "127.0.0.1",
                "MCP_PORT": "8001",
                "MCP_PATH": "/sse",
                "MCP_ALLOWED_ORIGINS": "http://127.0.0.1:3000",
                "MCP_LEGACY_MAX_SESSIONS": "16",
                "MCP_LEGACY_SESSION_IDLE_TIMEOUT_SECONDS": "10",
                "MCP_CALLER_ID": "demo-sse-client",
                "MCP_POLICY_PROFILE": "demo_readonly",
            }
        )


def test_load_sse_settings_rejects_wildcard_origin() -> None:
    from enterprise_data_mcp.bootstrap.settings import load_sse_settings

    with pytest.raises(ValueError, match="wildcard|Origin"):
        load_sse_settings(
            {
                "MCP_TRANSPORT": "sse",
                "MCP_HOST": "127.0.0.1",
                "MCP_PORT": "8001",
                "MCP_PATH": "/sse",
                "MCP_ALLOWED_ORIGINS": "*",
                "MCP_LEGACY_MAX_SESSIONS": "16",
                "MCP_LEGACY_SESSION_IDLE_TIMEOUT_SECONDS": "300",
                "MCP_CALLER_ID": "demo-sse-client",
                "MCP_POLICY_PROFILE": "demo_readonly",
            }
        )

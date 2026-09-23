"""RED: HTTP security — Origin / body / inflight (SPEC §15.4 / §4.5 / Step 11).

No production http_security until 11-GREEN.
"""

from __future__ import annotations

import pytest

from enterprise_data_mcp.domain.errors import TransportKind


def test_load_http_settings_binds_loopback_and_limits() -> None:
    from enterprise_data_mcp.bootstrap.settings import load_http_settings

    settings = load_http_settings(
        {
            "MCP_TRANSPORT": "streamable_http",
            "MCP_HOST": "127.0.0.1",
            "MCP_PORT": "8765",
            "MCP_PATH": "/mcp",
            "MCP_ALLOWED_ORIGINS": "http://127.0.0.1:3000,http://localhost:3000",
            "MCP_MAX_REQUEST_BODY_BYTES": "4096",
            "MCP_MAX_INFLIGHT_REQUESTS": "2",
            "MCP_CALLER_ID": "demo-http-client",
            "MCP_POLICY_PROFILE": "demo_readonly",
        }
    )
    assert settings.host == "127.0.0.1"
    assert settings.port == 8765
    assert settings.path == "/mcp"
    assert settings.allowed_origins == frozenset(
        {"http://127.0.0.1:3000", "http://localhost:3000"}
    )
    assert settings.max_request_body_bytes == 4096
    assert settings.max_inflight_requests == 2
    assert settings.transport == TransportKind.STREAMABLE_HTTP
    assert settings.caller_id == "demo-http-client"
    assert settings.policy_profile == "demo_readonly"


def test_load_http_settings_rejects_wildcard_origin() -> None:
    from enterprise_data_mcp.bootstrap.settings import load_http_settings

    with pytest.raises(ValueError, match="wildcard|Origin"):
        load_http_settings(
            {
                "MCP_TRANSPORT": "streamable_http",
                "MCP_HOST": "127.0.0.1",
                "MCP_PORT": "8000",
                "MCP_PATH": "/mcp",
                "MCP_ALLOWED_ORIGINS": "*",
                "MCP_MAX_REQUEST_BODY_BYTES": "1048576",
                "MCP_MAX_INFLIGHT_REQUESTS": "32",
                "MCP_CALLER_ID": "demo-http-client",
                "MCP_POLICY_PROFILE": "demo_readonly",
            }
        )


def test_load_http_settings_allows_container_any_host() -> None:
    from enterprise_data_mcp.bootstrap.settings import load_http_settings

    settings = load_http_settings(
        {
            "MCP_TRANSPORT": "streamable_http",
            "MCP_HOST": "0.0.0.0",
            "MCP_PORT": "8000",
            "MCP_PATH": "/mcp",
            "MCP_ALLOWED_ORIGINS": "http://127.0.0.1:3000",
            "MCP_MAX_REQUEST_BODY_BYTES": "1048576",
            "MCP_MAX_INFLIGHT_REQUESTS": "32",
            "MCP_CALLER_ID": "demo-http-client",
            "MCP_POLICY_PROFILE": "demo_readonly",
        }
    )
    assert settings.host == "0.0.0.0"


def test_load_http_settings_rejects_public_unicast_host() -> None:
    from enterprise_data_mcp.bootstrap.settings import load_http_settings

    with pytest.raises(ValueError, match="0.0.0.0|loopback"):
        load_http_settings(
            {
                "MCP_TRANSPORT": "streamable_http",
                "MCP_HOST": "8.8.8.8",
                "MCP_PORT": "8000",
                "MCP_PATH": "/mcp",
                "MCP_ALLOWED_ORIGINS": "http://127.0.0.1:3000",
                "MCP_MAX_REQUEST_BODY_BYTES": "1048576",
                "MCP_MAX_INFLIGHT_REQUESTS": "32",
                "MCP_CALLER_ID": "demo-http-client",
                "MCP_POLICY_PROFILE": "demo_readonly",
            }
        )


def test_origin_missing_allows_non_browser() -> None:
    from enterprise_data_mcp.hosts.http_security import decide_origin

    assert decide_origin(None, frozenset({"http://ok.example"})) == "allow"
    assert decide_origin("", frozenset({"http://ok.example"})) == "allow"


def test_origin_present_must_match_exact_allowlist() -> None:
    from enterprise_data_mcp.hosts.http_security import decide_origin

    allowed = frozenset({"http://127.0.0.1:3000"})
    assert decide_origin("http://127.0.0.1:3000", allowed) == "allow"
    assert decide_origin("http://evil.example", allowed) == "forbid"
    assert decide_origin("http://127.0.0.1:3000/", allowed) == "forbid"


def test_body_over_limit_is_rejected() -> None:
    from enterprise_data_mcp.hosts.http_security import decide_body_size

    assert decide_body_size(content_length=100, max_bytes=100) == "allow"
    assert decide_body_size(content_length=101, max_bytes=100) == "reject_413"
    assert decide_body_size(content_length=None, max_bytes=100) == "allow"


def test_inflight_limiter_returns_503_when_full() -> None:
    from enterprise_data_mcp.hosts.http_security import InflightLimiter

    limiter = InflightLimiter(max_inflight=1)
    assert limiter.try_acquire() is True
    assert limiter.try_acquire() is False  # would map to HTTP 503
    limiter.release()
    assert limiter.try_acquire() is True
    limiter.release()

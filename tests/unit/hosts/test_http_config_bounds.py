"""BUG-07-RED: HTTP/SSE Settings must reject out-of-range port/body/inflight (SPEC §12).

Approved bounds (BUG-07-PLAN):
  MCP_PORT: 1..65535
  MCP_MAX_REQUEST_BODY_BYTES: 1024..1048576
  MCP_MAX_INFLIGHT_REQUESTS: 1..128

No production changes in this Step.
"""

from __future__ import annotations

import pytest

from enterprise_data_mcp.domain.errors import TransportKind

_HTTP_BASE: dict[str, str] = {
    "MCP_TRANSPORT": "streamable_http",
    "MCP_HOST": "127.0.0.1",
    "MCP_ALLOWED_ORIGINS": "http://127.0.0.1",
    "MCP_CALLER_ID": "demo-http-client",
    "MCP_POLICY_PROFILE": "demo_readonly",
    "MCP_PORT": "8000",
    "MCP_MAX_REQUEST_BODY_BYTES": "1048576",
    "MCP_MAX_INFLIGHT_REQUESTS": "32",
}

_SSE_BASE: dict[str, str] = {
    "MCP_TRANSPORT": "sse",
    "MCP_HOST": "127.0.0.1",
    "MCP_ALLOWED_ORIGINS": "http://127.0.0.1",
    "MCP_CALLER_ID": "demo-sse-client",
    "MCP_POLICY_PROFILE": "demo_readonly",
    "MCP_PORT": "8001",
    "MCP_MAX_REQUEST_BODY_BYTES": "1048576",
    "MCP_MAX_INFLIGHT_REQUESTS": "32",
    "MCP_LEGACY_MAX_SESSIONS": "16",
    "MCP_LEGACY_SESSION_IDLE_TIMEOUT_SECONDS": "300",
}


def _http_env(**overrides: str) -> dict[str, str]:
    env = dict(_HTTP_BASE)
    env.update(overrides)
    return env


def _sse_env(**overrides: str) -> dict[str, str]:
    env = dict(_SSE_BASE)
    env.update(overrides)
    return env


# --- HTTP: illegal → must raise ---


@pytest.mark.parametrize(
    "overrides",
    [
        {"MCP_PORT": "0"},
        {"MCP_PORT": "65536"},
        {"MCP_MAX_REQUEST_BODY_BYTES": "1023"},
        {"MCP_MAX_REQUEST_BODY_BYTES": "1048577"},
        {"MCP_MAX_INFLIGHT_REQUESTS": "0"},
        {"MCP_MAX_INFLIGHT_REQUESTS": "129"},
    ],
)
def test_load_http_settings_rejects_out_of_range_port_body_inflight(
    overrides: dict[str, str],
) -> None:
    from enterprise_data_mcp.bootstrap.settings import load_http_settings

    with pytest.raises(ValueError):
        load_http_settings(_http_env(**overrides))


# --- HTTP: legal bounds → must bind ---


@pytest.mark.parametrize(
    ("overrides", "port", "body", "inflight"),
    [
        (
            {
                "MCP_PORT": "1",
                "MCP_MAX_REQUEST_BODY_BYTES": "1024",
                "MCP_MAX_INFLIGHT_REQUESTS": "1",
            },
            1,
            1024,
            1,
        ),
        (
            {
                "MCP_PORT": "65535",
                "MCP_MAX_REQUEST_BODY_BYTES": "1048576",
                "MCP_MAX_INFLIGHT_REQUESTS": "128",
            },
            65535,
            1048576,
            128,
        ),
    ],
)
def test_load_http_settings_accepts_boundary_port_body_inflight(
    overrides: dict[str, str],
    port: int,
    body: int,
    inflight: int,
) -> None:
    from enterprise_data_mcp.bootstrap.settings import load_http_settings

    settings = load_http_settings(_http_env(**overrides))
    assert settings.port == port
    assert settings.max_request_body_bytes == body
    assert settings.max_inflight_requests == inflight
    assert settings.transport == TransportKind.STREAMABLE_HTTP


# --- SSE: illegal (mirror) ---


@pytest.mark.parametrize(
    "overrides",
    [
        {"MCP_PORT": "0"},
        {"MCP_MAX_REQUEST_BODY_BYTES": "1023"},
        {"MCP_MAX_INFLIGHT_REQUESTS": "0"},
    ],
)
def test_load_sse_settings_rejects_out_of_range_port_body_inflight(
    overrides: dict[str, str],
) -> None:
    from enterprise_data_mcp.bootstrap.settings import load_sse_settings

    with pytest.raises(ValueError):
        load_sse_settings(_sse_env(**overrides))


# --- SSE: legal bound ---


def test_load_sse_settings_accepts_boundary_port_body_inflight() -> None:
    from enterprise_data_mcp.bootstrap.settings import load_sse_settings

    settings = load_sse_settings(
        _sse_env(
            MCP_PORT="65535",
            MCP_MAX_REQUEST_BODY_BYTES="1024",
            MCP_MAX_INFLIGHT_REQUESTS="128",
        )
    )
    assert settings.port == 65535
    assert settings.max_request_body_bytes == 1024
    assert settings.max_inflight_requests == 128
    assert settings.transport == TransportKind.SSE

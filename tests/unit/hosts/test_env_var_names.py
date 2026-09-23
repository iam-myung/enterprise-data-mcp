"""BUG-05-RED: Settings must read MCP_CALLER_ID / MCP_POLICY_PROFILE (SPEC §12).

Authoritative env names (PLAN):
  MCP_CALLER_ID → settings.caller_id
  MCP_POLICY_PROFILE → settings.policy_profile

Deprecated (must not be read):
  CALLER_ID, POLICY_PROFILE

No production changes in this Step.
"""

from __future__ import annotations

from enterprise_data_mcp.domain.errors import TransportKind

# Distinct from Settings defaults so RED cannot pass by coincidence.
_BUG05_CALLER = "bug05-caller"
_BUG05_PROFILE = "bug05-profile"
_LEGACY_CALLER = "legacy-caller-must-not-bind"
_LEGACY_PROFILE = "legacy-profile-must-not-bind"


def test_load_stdio_settings_binds_mcp_caller_and_policy_env_names() -> None:
    from enterprise_data_mcp.bootstrap.settings import load_stdio_settings

    settings = load_stdio_settings(
        {
            "MCP_TRANSPORT": "stdio",
            "MCP_CALLER_ID": _BUG05_CALLER,
            "MCP_POLICY_PROFILE": _BUG05_PROFILE,
        }
    )
    assert settings.caller_id == _BUG05_CALLER
    assert settings.policy_profile == _BUG05_PROFILE
    assert settings.transport == TransportKind.STDIO


def test_load_http_settings_binds_mcp_caller_and_policy_env_names() -> None:
    from enterprise_data_mcp.bootstrap.settings import load_http_settings

    settings = load_http_settings(
        {
            "MCP_TRANSPORT": "streamable_http",
            "MCP_HOST": "127.0.0.1",
            "MCP_ALLOWED_ORIGINS": "http://127.0.0.1",
            "MCP_CALLER_ID": _BUG05_CALLER,
            "MCP_POLICY_PROFILE": _BUG05_PROFILE,
        }
    )
    assert settings.caller_id == _BUG05_CALLER
    assert settings.policy_profile == _BUG05_PROFILE
    assert settings.transport == TransportKind.STREAMABLE_HTTP


def test_load_sse_settings_binds_mcp_caller_and_policy_env_names() -> None:
    from enterprise_data_mcp.bootstrap.settings import load_sse_settings

    settings = load_sse_settings(
        {
            "MCP_TRANSPORT": "sse",
            "MCP_HOST": "127.0.0.1",
            "MCP_ALLOWED_ORIGINS": "http://127.0.0.1",
            "MCP_CALLER_ID": _BUG05_CALLER,
            "MCP_POLICY_PROFILE": _BUG05_PROFILE,
        }
    )
    assert settings.caller_id == _BUG05_CALLER
    assert settings.policy_profile == _BUG05_PROFILE
    assert settings.transport == TransportKind.SSE


def test_load_stdio_settings_ignores_deprecated_caller_and_policy_env_names() -> None:
    from enterprise_data_mcp.bootstrap.settings import load_stdio_settings

    settings = load_stdio_settings(
        {
            "MCP_TRANSPORT": "stdio",
            "CALLER_ID": _LEGACY_CALLER,
            "POLICY_PROFILE": _LEGACY_PROFILE,
        }
    )
    assert settings.caller_id != _LEGACY_CALLER
    assert settings.policy_profile != _LEGACY_PROFILE

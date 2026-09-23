"""Host settings — stdio (Step 10) and Streamable HTTP (Step 11)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from enterprise_data_mcp.domain.errors import TransportKind

_DEFAULT_CALLER_ID = "demo-stdio-client"
_DEFAULT_POLICY_PROFILE = "demo_readonly"
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_CONTAINER_ANY_HOST = "0.0.0.0"
_ALLOWED_BIND_HOSTS = _LOOPBACK_HOSTS | {_CONTAINER_ANY_HOST}


def _require_bind_host(host: str) -> str:
    """SPEC §12 / §15.1.1: loopback or container INADDR_ANY only."""
    if host not in _ALLOWED_BIND_HOSTS:
        raise ValueError(
            "V1 MCP_HOST must be loopback (127.0.0.1/localhost/::1) "
            f"or container bind 0.0.0.0, got {host!r}"
        )
    return host


def _require_tcp_port(port: int) -> int:
    if not 1 <= port <= 65535:
        raise ValueError(f"MCP_PORT must be in 1..65535, got {port}")
    return port


def _require_max_request_body_bytes(body: int) -> int:
    if not 1024 <= body <= 1_048_576:
        raise ValueError(
            f"MCP_MAX_REQUEST_BODY_BYTES must be in 1024..1048576, got {body}"
        )
    return body


def _require_max_inflight_requests(inflight: int) -> int:
    if not 1 <= inflight <= 128:
        raise ValueError(
            f"MCP_MAX_INFLIGHT_REQUESTS must be in 1..128, got {inflight}"
        )
    return inflight


@dataclass(frozen=True, slots=True)
class StdioHostSettings:
    caller_id: str
    policy_profile: str
    transport: TransportKind


@dataclass(frozen=True, slots=True)
class HttpHostSettings:
    caller_id: str
    policy_profile: str
    transport: TransportKind
    host: str
    port: int
    path: str
    allowed_origins: frozenset[str]
    max_request_body_bytes: int
    max_inflight_requests: int


@dataclass(frozen=True, slots=True)
class SseHostSettings:
    caller_id: str
    policy_profile: str
    transport: TransportKind
    host: str
    port: int
    path: str
    allowed_origins: frozenset[str]
    max_request_body_bytes: int
    max_inflight_requests: int
    legacy_max_sessions: int
    legacy_session_idle_timeout_seconds: int


def load_stdio_settings(
    environ: Mapping[str, str] | None = None,
) -> StdioHostSettings:
    env = environ if environ is not None else {}
    transport_raw = str(env.get("MCP_TRANSPORT", "stdio")).strip().lower()
    if transport_raw != "stdio":
        raise ValueError(f"stdio host requires MCP_TRANSPORT=stdio, got {transport_raw!r}")
    return StdioHostSettings(
        caller_id=str(env.get("MCP_CALLER_ID", _DEFAULT_CALLER_ID)),
        policy_profile=str(env.get("MCP_POLICY_PROFILE", _DEFAULT_POLICY_PROFILE)),
        transport=TransportKind.STDIO,
    )


def load_http_settings(
    environ: Mapping[str, str] | None = None,
) -> HttpHostSettings:
    env = environ if environ is not None else {}
    transport_raw = str(env.get("MCP_TRANSPORT", "streamable_http")).strip().lower()
    if transport_raw not in {"streamable_http", "streamable-http"}:
        raise ValueError(
            f"http host requires MCP_TRANSPORT=streamable_http, got {transport_raw!r}"
        )

    host = _require_bind_host(str(env.get("MCP_HOST", "127.0.0.1")).strip())

    origins_raw = str(env.get("MCP_ALLOWED_ORIGINS", "http://127.0.0.1")).strip()
    if not origins_raw:
        raise ValueError("MCP_ALLOWED_ORIGINS is required for HTTP Host")
    parts = [p.strip() for p in origins_raw.split(",") if p.strip()]
    if any(p == "*" or "*" in p for p in parts):
        raise ValueError("Origin allowlist forbids wildcard entries")
    allowed_origins = frozenset(parts)

    body = _require_max_request_body_bytes(
        int(env.get("MCP_MAX_REQUEST_BODY_BYTES", "1048576"))
    )
    inflight = _require_max_inflight_requests(
        int(env.get("MCP_MAX_INFLIGHT_REQUESTS", "32"))
    )
    port = _require_tcp_port(int(env.get("MCP_PORT", "8000")))
    path = str(env.get("MCP_PATH", "/mcp")).strip() or "/mcp"

    return HttpHostSettings(
        caller_id=str(env.get("MCP_CALLER_ID", "demo-http-client")),
        policy_profile=str(env.get("MCP_POLICY_PROFILE", _DEFAULT_POLICY_PROFILE)),
        transport=TransportKind.STREAMABLE_HTTP,
        host=host,
        port=port,
        path=path,
        allowed_origins=allowed_origins,
        max_request_body_bytes=body,
        max_inflight_requests=inflight,
    )


def load_sse_settings(
    environ: Mapping[str, str] | None = None,
) -> SseHostSettings:
    env = environ if environ is not None else {}
    transport_raw = str(env.get("MCP_TRANSPORT", "sse")).strip().lower()
    if transport_raw != "sse":
        raise ValueError(f"sse host requires MCP_TRANSPORT=sse, got {transport_raw!r}")

    host = _require_bind_host(str(env.get("MCP_HOST", "127.0.0.1")).strip())

    origins_raw = str(env.get("MCP_ALLOWED_ORIGINS", "http://127.0.0.1")).strip()
    if not origins_raw:
        raise ValueError("MCP_ALLOWED_ORIGINS is required for HTTP Host")
    parts = [p.strip() for p in origins_raw.split(",") if p.strip()]
    if any(p == "*" or "*" in p for p in parts):
        raise ValueError("Origin allowlist forbids wildcard entries")
    allowed_origins = frozenset(parts)

    max_sessions = int(env.get("MCP_LEGACY_MAX_SESSIONS", "16"))
    if not 1 <= max_sessions <= 64:
        raise ValueError("legacy max sessions must be in 1..64")

    idle = int(env.get("MCP_LEGACY_SESSION_IDLE_TIMEOUT_SECONDS", "300"))
    if not 30 <= idle <= 900:
        raise ValueError("legacy idle timeout must be in 30..900 seconds")

    body = _require_max_request_body_bytes(
        int(env.get("MCP_MAX_REQUEST_BODY_BYTES", "1048576"))
    )
    inflight = _require_max_inflight_requests(
        int(env.get("MCP_MAX_INFLIGHT_REQUESTS", "32"))
    )
    port = _require_tcp_port(int(env.get("MCP_PORT", "8001")))
    path = str(env.get("MCP_PATH", "/sse")).strip() or "/sse"

    return SseHostSettings(
        caller_id=str(env.get("MCP_CALLER_ID", "demo-sse-client")),
        policy_profile=str(env.get("MCP_POLICY_PROFILE", _DEFAULT_POLICY_PROFILE)),
        transport=TransportKind.SSE,
        host=host,
        port=port,
        path=path,
        allowed_origins=allowed_origins,
        max_request_body_bytes=body,
        max_inflight_requests=inflight,
        legacy_max_sessions=max_sessions,
        legacy_session_idle_timeout_seconds=idle,
    )

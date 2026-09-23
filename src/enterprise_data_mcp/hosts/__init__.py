"""Transport hosts — stdio + Streamable HTTP + legacy SSE (Steps 10–12)."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.routing import Route

from enterprise_data_mcp.adapters.inbound.mcp.compose import compose_enterprise_mcp
from enterprise_data_mcp.bootstrap.container import AppContainer
from enterprise_data_mcp.bootstrap.settings import HttpHostSettings, SseHostSettings
from enterprise_data_mcp.hosts.health import demo_readiness, healthz_response, readyz_response
from enterprise_data_mcp.hosts.http_security import (
    HttpSecurityMiddleware,
    InflightLimiter,
)
from enterprise_data_mcp.hosts.sse_session import LegacySessionLimiter

HANDSHAKE_SERVER_NAME = "enterprise-data-mcp-handshake"


def build_handshake_server() -> FastMCP:
    """Return a FastMCP instance with no business tools/resources (Step 1)."""
    return FastMCP(HANDSHAKE_SERVER_NAME)


def build_stdio_server(*, container: AppContainer) -> FastMCP:
    """Assemble inbound MCP surface for the stdio Host."""
    return compose_enterprise_mcp(
        list_datasets=container.list_datasets,
        get_schema=container.get_schema,
        execute_query=container.execute_query,
        caller=container.caller,
        call_id=container.call_id,
    )


def build_streamable_http_server(*, container: AppContainer) -> FastMCP:
    """Assemble inbound MCP surface for the Streamable HTTP Host."""
    return compose_enterprise_mcp(
        list_datasets=container.list_datasets,
        get_schema=container.get_schema,
        execute_query=container.execute_query,
        caller=container.caller,
        call_id=container.call_id,
    )


def build_sse_server(*, container: AppContainer) -> FastMCP:
    """Assemble inbound MCP surface for the legacy SSE Host (no new capabilities)."""
    return compose_enterprise_mcp(
        list_datasets=container.list_datasets,
        get_schema=container.get_schema,
        execute_query=container.execute_query,
        caller=container.caller,
        call_id=container.call_id,
    )


def build_streamable_http_app(
    *,
    container: AppContainer,
    settings: HttpHostSettings,
) -> Starlette:
    """ASGI app: /healthz · /readyz · /mcp + Origin/body/inflight middleware."""
    mcp = build_streamable_http_server(container=container)
    mcp_app = mcp.http_app(path=settings.path, transport="streamable-http")
    limiter = InflightLimiter(max_inflight=settings.max_inflight_requests)
    readiness = demo_readiness()

    async def healthz(_request: Any) -> JSONResponse:
        status, body = healthz_response()
        return JSONResponse(body, status_code=status)

    async def readyz(_request: Any) -> JSONResponse:
        status, body = readyz_response(readiness)
        return JSONResponse(body, status_code=status)

    app = Starlette(
        routes=[
            Route("/healthz", healthz, methods=["GET"]),
            Route("/readyz", readyz, methods=["GET"]),
            *list(mcp_app.routes),
        ],
        middleware=[
            Middleware(
                HttpSecurityMiddleware,
                allowed_origins=settings.allowed_origins,
                max_request_body_bytes=settings.max_request_body_bytes,
                limiter=limiter,
            )
        ],
        lifespan=getattr(mcp_app, "lifespan", None),
    )
    app.state.inflight_limiter = limiter
    return app


def build_sse_app(
    *,
    container: AppContainer,
    settings: SseHostSettings,
) -> Starlette:
    """ASGI app: /healthz · /sse · /messages + shared security + session limiter."""
    mcp = build_sse_server(container=container)
    mcp_app = mcp.http_app(path=settings.path, transport="sse")
    inflight = InflightLimiter(max_inflight=settings.max_inflight_requests)
    sessions = LegacySessionLimiter(
        max_sessions=settings.legacy_max_sessions,
        idle_timeout_seconds=settings.legacy_session_idle_timeout_seconds,
    )
    readiness = demo_readiness()

    async def healthz(_request: Any) -> JSONResponse:
        status, body = healthz_response()
        return JSONResponse(body, status_code=status)

    async def readyz(_request: Any) -> JSONResponse:
        sessions.evict_idle()
        status, body = readyz_response(readiness)
        return JSONResponse(body, status_code=status)

    app = Starlette(
        routes=[
            Route("/healthz", healthz, methods=["GET"]),
            Route("/readyz", readyz, methods=["GET"]),
            *list(mcp_app.routes),
        ],
        middleware=[
            Middleware(
                HttpSecurityMiddleware,
                allowed_origins=settings.allowed_origins,
                max_request_body_bytes=settings.max_request_body_bytes,
                limiter=inflight,
                sse_path=settings.path,
            )
        ],
        lifespan=getattr(mcp_app, "lifespan", None),
    )
    app.state.inflight_limiter = inflight
    app.state.session_limiter = sessions
    return app

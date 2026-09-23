"""RED: Legacy SSE Host contract — same business surface, no new capabilities (Step 12).

Old-client path + session limit; assert Tool/Resource closure ≡ chapter 9.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

_DATASETS_URI = "enterprise-data://datasets"
_TOOL_NAME = "query_data"
_PHYSICAL = "phys_sales_secret"
_CALLER_ID = "demo-sse-client"
_POLICY_PROFILE = "demo_readonly"
_ALLOWED_ORIGIN = "http://127.0.0.1:3000"
_ALLOWED_TOOLS = frozenset({_TOOL_NAME})
_FORBIDDEN_TOOL_NAMES = frozenset(
    {"execute_sql", "raw_sql", "run_sql", "sampling", "orchestrate"}
)


def _env() -> dict[str, str]:
    return {
        "MCP_TRANSPORT": "sse",
        "MCP_HOST": "127.0.0.1",
        "MCP_PORT": "8001",
        "MCP_PATH": "/sse",
        "MCP_ALLOWED_ORIGINS": _ALLOWED_ORIGIN,
        "MCP_MAX_REQUEST_BODY_BYTES": "1048576",
        "MCP_MAX_INFLIGHT_REQUESTS": "32",
        "MCP_LEGACY_MAX_SESSIONS": "2",
        "MCP_LEGACY_SESSION_IDLE_TIMEOUT_SECONDS": "30",
        "MCP_CALLER_ID": _CALLER_ID,
        "MCP_POLICY_PROFILE": _POLICY_PROFILE,
        "ENTERPRISE_DATA_MCP_SSE_DEMO": "1",
    }


def _build_app() -> Any:
    from enterprise_data_mcp.bootstrap.container import build_demo_container
    from enterprise_data_mcp.bootstrap.settings import load_sse_settings
    from enterprise_data_mcp.hosts import build_sse_app

    settings = load_sse_settings(_env())
    container = build_demo_container(settings)
    return build_sse_app(container=container, settings=settings)


def test_sse_app_exposes_health_and_messages_route() -> None:
    app = _build_app()

    async def _run() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            hz = await client.get("/healthz")
            assert hz.status_code == 200
            assert hz.json() == {"status": "ok"}

            # /messages must exist (method may be limited); 404 = missing surface
            messages = await client.get("/messages/")
            assert messages.status_code != 404

            sse = await client.get("/sse")
            # Route exists (may be 405/406 without Accept); not 404
            assert sse.status_code != 404

    asyncio.run(_run())


def test_sse_forbidden_origin_returns_403() -> None:
    app = _build_app()

    async def _run() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            resp = await client.post(
                "/messages/",
                headers={
                    "Origin": "http://evil.example",
                    "Content-Type": "application/json",
                },
                content=b"{}",
            )
            assert resp.status_code == 403

    asyncio.run(_run())


def test_sse_session_limit_returns_503_via_app_state() -> None:
    from enterprise_data_mcp.hosts.sse_session import LegacySessionLimiter

    app = _build_app()
    hold = getattr(app, "state", None)
    assert hold is not None
    limiter = getattr(hold, "session_limiter", None)
    assert isinstance(limiter, LegacySessionLimiter)
    assert limiter.try_open("a") is True
    assert limiter.try_open("b") is True
    assert limiter.try_open("c") is False


def test_sse_mcp_surface_matches_chapter9_closure_no_new_tools() -> None:
    """In-process composed surface: only datasets/schema/query_data — no new capabilities."""
    from enterprise_data_mcp.bootstrap.container import build_demo_container
    from enterprise_data_mcp.bootstrap.settings import load_sse_settings
    from enterprise_data_mcp.hosts import build_sse_server

    settings = load_sse_settings(_env())
    container = build_demo_container(settings)
    mcp = build_sse_server(container=container)

    async def _run() -> None:
        resources = await mcp.list_resources()
        uris = {str(r.uri) for r in resources}
        assert _DATASETS_URI in uris

        templates = await mcp.list_resource_templates()
        template_uris = {str(t.uri_template) for t in templates}
        assert any("datasets/{dataset_id}/schema" in u for u in template_uris)

        tools = await mcp.list_tools()
        names = {t.name for t in tools}
        assert names == _ALLOWED_TOOLS
        assert names.isdisjoint(_FORBIDDEN_TOOL_NAMES)

        listed = await mcp.read_resource(_DATASETS_URI)
        raw = listed.contents[0].content
        payload = json.loads(raw)
        assert payload["success"] is True
        assert _PHYSICAL not in raw

    asyncio.run(_run())

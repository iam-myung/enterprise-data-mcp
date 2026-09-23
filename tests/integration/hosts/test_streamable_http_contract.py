"""RED: Streamable HTTP Host contract vectors (SPEC Step 11 / API §2 / §15.4).

Origin/body/inflight/health via ASGI; /mcp business surface. No GREEN yet.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

_DATASETS_URI = "enterprise-data://datasets"
_TOOL_NAME = "query_data"
_DATASET = "sales_inventory_daily"
_PHYSICAL = "phys_sales_secret"
_CALLER_ID = "demo-http-client"
_POLICY_PROFILE = "demo_readonly"
_ALLOWED_ORIGIN = "http://127.0.0.1:3000"


def _env() -> dict[str, str]:
    return {
        "MCP_TRANSPORT": "streamable_http",
        "MCP_HOST": "127.0.0.1",
        "MCP_PORT": "8000",
        "MCP_PATH": "/mcp",
        "MCP_ALLOWED_ORIGINS": _ALLOWED_ORIGIN,
        "MCP_MAX_REQUEST_BODY_BYTES": "1024",
        "MCP_MAX_INFLIGHT_REQUESTS": "1",
        "MCP_CALLER_ID": _CALLER_ID,
        "MCP_POLICY_PROFILE": _POLICY_PROFILE,
        "ENTERPRISE_DATA_MCP_HTTP_DEMO": "1",
    }


def _build_app() -> Any:
    from enterprise_data_mcp.bootstrap.container import build_demo_container
    from enterprise_data_mcp.bootstrap.settings import load_http_settings
    from enterprise_data_mcp.hosts import build_streamable_http_app

    settings = load_http_settings(_env())
    container = build_demo_container(settings)  # type: ignore[arg-type]
    return build_streamable_http_app(container=container, settings=settings)


def test_healthz_and_readyz_via_asgi() -> None:
    app = _build_app()

    async def _run() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            hz = await client.get("/healthz")
            assert hz.status_code == 200
            assert hz.json() == {"status": "ok"}

            rz = await client.get("/readyz")
            assert rz.status_code == 200
            assert rz.json() == {"status": "ready"}

    asyncio.run(_run())


def test_forbidden_origin_returns_403() -> None:
    app = _build_app()

    async def _run() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            resp = await client.post(
                "/mcp",
                headers={"Origin": "http://evil.example", "Content-Type": "application/json"},
                content=b"{}",
            )
            assert resp.status_code == 403

    asyncio.run(_run())


def test_oversized_body_returns_413() -> None:
    app = _build_app()

    async def _run() -> None:
        transport = httpx.ASGITransport(app=app)
        body = b"x" * 1100  # > MCP_MAX_REQUEST_BODY_BYTES=1024
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            resp = await client.post(
                "/mcp",
                headers={
                    "Origin": _ALLOWED_ORIGIN,
                    "Content-Type": "application/json",
                    "Content-Length": str(len(body)),
                },
                content=body,
            )
            assert resp.status_code == 413

    asyncio.run(_run())


def test_inflight_limit_returns_503() -> None:
    from enterprise_data_mcp.hosts.http_security import InflightLimiter

    # Unit-shaped contract also enforced on the app via shared limiter.
    # Hold one slot, then assert a second request would be rejected.
    limiter = InflightLimiter(max_inflight=1)
    assert limiter.try_acquire() is True
    assert limiter.try_acquire() is False

    app = _build_app()

    async def _run() -> None:
        # App factory must expose the same limiter semantics: max_inflight=1 from settings.
        # Drive two overlapping requests; second must be 503.
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            # Use a blocking-friendly probe: GET /readyz holds no lock long-term;
            # instead call the app's documented probe endpoint or POST /mcp with
            # Origin allowed while artificially holding the limiter via app.state.
            hold = getattr(app, "state", None)
            assert hold is not None, "ASGI app must expose state for inflight limiter"
            app_limiter = getattr(hold, "inflight_limiter", None)
            assert isinstance(app_limiter, InflightLimiter)
            assert app_limiter.try_acquire() is True
            try:
                resp = await client.get("/readyz")
                # Even readyz is subject to inflight cap when full.
                assert resp.status_code == 503
            finally:
                app_limiter.release()

    asyncio.run(_run())


def test_asgi_mcp_surface_lists_datasets_resource() -> None:
    """In-process composed surface behind HTTP app factory (not handshake-only)."""
    from enterprise_data_mcp.bootstrap.container import build_demo_container
    from enterprise_data_mcp.bootstrap.settings import load_http_settings
    from enterprise_data_mcp.hosts import build_streamable_http_server

    settings = load_http_settings(_env())
    container = build_demo_container(settings)  # type: ignore[arg-type]
    mcp = build_streamable_http_server(container=container)

    async def _run() -> None:
        resources = await mcp.list_resources()
        uris = {str(r.uri) for r in resources}
        assert _DATASETS_URI in uris
        tools = await mcp.list_tools()
        names = {t.name for t in tools}
        assert _TOOL_NAME in names
        assert "execute_sql" not in names

        listed = await mcp.read_resource(_DATASETS_URI)
        raw = listed.contents[0].content
        payload = json.loads(raw)
        assert payload["success"] is True
        assert _PHYSICAL not in raw

    asyncio.run(_run())

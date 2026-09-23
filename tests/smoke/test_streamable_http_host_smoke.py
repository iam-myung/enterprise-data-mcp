"""Step 11 SMOKE: real Streamable HTTP Host (SPEC §18.4 / §15.4 Primary Transport Gate).

Uvicorn 启停 · /mcp · 403/413/503 · 端口释放.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import anyio
import httpx
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

PROJECT_ROOT = Path(__file__).resolve().parents[2]

_DATASETS_URI = "enterprise-data://datasets"
_TOOL_NAME = "query_data"
_PHYSICAL = "phys_sales_secret"
_CALLER_ID = "demo-http-client"
_POLICY_PROFILE = "demo_readonly"
_ALLOWED_ORIGIN = "http://127.0.0.1:3000"
_PRIMARY_PROTOCOL = "2026-07-28"
_HOST = "127.0.0.1"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind((_HOST, 0))
        return int(sock.getsockname()[1])


def _wait_for_port(port: int, timeout: float = 45.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((_HOST, port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)
    raise RuntimeError(f"streamable-http host did not listen on {_HOST}:{port}")


def _assert_port_closed(port: int, timeout: float = 8.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((_HOST, port), timeout=0.2):
                time.sleep(0.05)
        except OSError:
            return
    raise AssertionError(f"port {_HOST}:{port} still accepting after teardown")


@contextmanager
def _streamable_http_process(
    *,
    max_body: int = 256,
    max_inflight: int = 1,
) -> Iterator[tuple[subprocess.Popen[bytes], int, str]]:
    port = _free_port()
    env = {
        **os.environ,
        "MCP_TRANSPORT": "streamable_http",
        "MCP_HOST": _HOST,
        "MCP_PORT": str(port),
        "MCP_PATH": "/mcp",
        "MCP_ALLOWED_ORIGINS": _ALLOWED_ORIGIN,
        "MCP_MAX_REQUEST_BODY_BYTES": str(max_body),
        "MCP_MAX_INFLIGHT_REQUESTS": str(max_inflight),
        "MCP_CALLER_ID": _CALLER_ID,
        "MCP_POLICY_PROFILE": _POLICY_PROFILE,
        "MCP_CONTAINER": "demo",
        "ENTERPRISE_DATA_MCP_HTTP_DEMO": "1",
        "PYTHONUNBUFFERED": "1",
    }
    proc = subprocess.Popen(
        [sys.executable, "-u", "-m", "enterprise_data_mcp.hosts.streamable_http"],
        cwd=str(PROJECT_ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_for_port(port)
        yield proc, port, f"http://{_HOST}:{port}/mcp"
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=3)
        assert proc.poll() is not None, "streamable_http process still alive"
        _assert_port_closed(port)


def test_streamable_http_health_ready_and_mcp_list() -> None:
    """Real process: /healthz · /readyz · protocol + list resources."""
    # MCP Streamable HTTP needs concurrent HTTP streams; keep inflight headroom.
    with _streamable_http_process(max_body=1048576, max_inflight=32) as (
        proc,
        port,
        mcp_url,
    ):
        assert proc.poll() is None

        health = httpx.get(f"http://{_HOST}:{port}/healthz", timeout=5.0)
        assert health.status_code == 200
        assert health.json() == {"status": "ok"}

        ready = httpx.get(f"http://{_HOST}:{port}/readyz", timeout=5.0)
        assert ready.status_code == 200
        assert ready.json() == {"status": "ready"}

        async def _mcp() -> dict[str, Any]:
            async with Client(StreamableHttpTransport(mcp_url)) as client:
                version = client.protocol_version
                resources = await client.list_resources()
                tools = await client.list_tools()
                listed = await client.read_resource(_DATASETS_URI)
                return {
                    "version": version,
                    "uris": {str(r.uri) for r in resources},
                    "names": {t.name for t in tools},
                    "listed": listed,
                }

        out = anyio.run(_mcp)
        assert out["version"] == _PRIMARY_PROTOCOL
        assert _DATASETS_URI in out["uris"]
        assert _TOOL_NAME in out["names"]
        assert "execute_sql" not in out["names"]

        listed = out["listed"]
        raw = listed[0].text if isinstance(listed, list) else listed.contents[0].content
        payload = json.loads(raw)
        assert payload["success"] is True
        assert _PHYSICAL not in raw


def test_streamable_http_403_413_503_and_port_cleanup() -> None:
    """Real process probes: forbidden Origin · oversized body · inflight 503."""
    # Body floor is 1024 (BUG-07); oversized probe must exceed that floor.
    with _streamable_http_process(max_body=1024, max_inflight=1) as (proc, port, _mcp_url):
        assert proc.poll() is None
        base = f"http://{_HOST}:{port}"

        forbidden = httpx.post(
            f"{base}/mcp",
            headers={
                "Origin": "http://evil.example",
                "Content-Type": "application/json",
            },
            content=b"{}",
            timeout=5.0,
        )
        assert forbidden.status_code == 403

        body = b"x" * 1100
        oversized = httpx.post(
            f"{base}/mcp",
            headers={
                "Origin": _ALLOWED_ORIGIN,
                "Content-Type": "application/json",
                "Content-Length": str(len(body)),
            },
            content=body,
            timeout=5.0,
        )
        assert oversized.status_code == 413

        # Hold one inflight slot with a raw socket stalled mid-body (async GETs alone
        # finish too fast to overlap under single-worker Uvicorn).
        holder = socket.create_connection((_HOST, port), timeout=5)
        try:
            stall = (
                f"POST /mcp HTTP/1.1\r\n"
                f"Host: {_HOST}:{port}\r\n"
                f"Origin: {_ALLOWED_ORIGIN}\r\n"
                f"Content-Type: application/json\r\n"
                f"Content-Length: 50\r\n"
                f"\r\n"
                "{"
            ).encode("ascii")
            holder.sendall(stall)
            time.sleep(0.4)
            probes = [
                httpx.get(f"{base}/readyz", timeout=5.0).status_code for _ in range(6)
            ]
        finally:
            holder.close()

        assert 503 in probes, f"expected inflight 503 under max=1, got {probes!r}"

    # contextmanager already asserts process exit + port closed

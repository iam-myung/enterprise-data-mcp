"""Step 12 SMOKE: real legacy SSE Host (SPEC §18.4 Legacy Compatibility Gate).

连接/断开 · /messages · 协议 2025-11-25 · Session 清理 · 端口释放.
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
from fastmcp.client.transports import SSETransport

PROJECT_ROOT = Path(__file__).resolve().parents[2]

_DATASETS_URI = "enterprise-data://datasets"
_TOOL_NAME = "query_data"
_PHYSICAL = "phys_sales_secret"
_CALLER_ID = "demo-sse-client"
_POLICY_PROFILE = "demo_readonly"
_ALLOWED_ORIGIN = "http://127.0.0.1:3000"
_LEGACY_PROTOCOL = "2025-11-25"
_HOST = "127.0.0.1"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind((_HOST, 0))
        return int(sock.getsockname()[1])


def _wait_for_port(port: int, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((_HOST, port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)
    raise RuntimeError(f"sse host did not listen on {_HOST}:{port}")


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
def _sse_host_process(
    *,
    max_sessions: int = 16,
    idle_timeout: int = 30,
) -> Iterator[tuple[subprocess.Popen[bytes], int, str]]:
    port = _free_port()
    env = {
        **os.environ,
        "MCP_TRANSPORT": "sse",
        "MCP_HOST": _HOST,
        "MCP_PORT": str(port),
        "MCP_PATH": "/sse",
        "MCP_ALLOWED_ORIGINS": _ALLOWED_ORIGIN,
        "MCP_MAX_REQUEST_BODY_BYTES": "1048576",
        "MCP_MAX_INFLIGHT_REQUESTS": "32",
        "MCP_LEGACY_MAX_SESSIONS": str(max_sessions),
        "MCP_LEGACY_SESSION_IDLE_TIMEOUT_SECONDS": str(idle_timeout),
        "MCP_CALLER_ID": _CALLER_ID,
        "MCP_POLICY_PROFILE": _POLICY_PROFILE,
        "ENTERPRISE_DATA_MCP_SSE_DEMO": "1",
        "PYTHONUNBUFFERED": "1",
    }
    proc = subprocess.Popen(
        [sys.executable, "-u", "-m", "enterprise_data_mcp.hosts.sse"],
        cwd=str(PROJECT_ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_for_port(port)
        yield proc, port, f"http://{_HOST}:{port}/sse"
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=3)
        assert proc.poll() is not None, "sse process still alive after teardown"
        _assert_port_closed(port)


def test_sse_host_legacy_protocol_messages_and_surface() -> None:
    """Real process: /messages · compat protocol · list resources · no new tools."""
    with _sse_host_process() as (proc, port, sse_url):
        assert proc.poll() is None
        base = f"http://{_HOST}:{port}"

        health = httpx.get(f"{base}/healthz", timeout=5.0)
        assert health.status_code == 200
        assert health.json() == {"status": "ok"}

        messages = httpx.get(f"{base}/messages/", timeout=5.0)
        assert messages.status_code != 404, "/messages route missing"

        async def _mcp() -> dict[str, Any]:
            async with Client(SSETransport(sse_url)) as client:
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
        assert out["version"] == _LEGACY_PROTOCOL
        assert _DATASETS_URI in out["uris"]
        assert out["names"] == {_TOOL_NAME}
        assert "execute_sql" not in out["names"]
        assert "sampling" not in out["names"]

        listed = out["listed"]
        raw = listed[0].text if isinstance(listed, list) else listed.contents[0].content
        payload = json.loads(raw)
        assert payload["success"] is True
        assert _PHYSICAL not in raw


def test_sse_host_reconnect_after_disconnect_and_session_cleanup() -> None:
    """Connect → disconnect → reconnect; process teardown frees port (Legacy Gate)."""
    with _sse_host_process(max_sessions=2, idle_timeout=30) as (proc, port, sse_url):
        assert proc.poll() is None

        async def _session_roundtrip() -> str:
            async with Client(SSETransport(sse_url)) as client:
                version = client.protocol_version
                assert version is not None
                tools = await client.list_tools()
                assert {t.name for t in tools} == {_TOOL_NAME}
                return version

        # First session
        v1 = anyio.run(_session_roundtrip)
        assert v1 == _LEGACY_PROTOCOL

        # After disconnect, a new session must succeed (slot / connection cleaned).
        v2 = anyio.run(_session_roundtrip)
        assert v2 == _LEGACY_PROTOCOL

        # readyz triggers idle eviction path without leaking details
        ready = httpx.get(f"http://{_HOST}:{port}/readyz", timeout=5.0)
        assert ready.status_code == 200
        assert ready.json() == {"status": "ready"}

    # contextmanager asserts process exit + port closed

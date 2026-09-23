"""Step 1 SMOKE: real stdio / Streamable HTTP / legacy SSE handshakes (SPEC §18.4)."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import tomllib
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import anyio
import httpx2
import pytest
from fastmcp import Client
from fastmcp.client.transports import (
    SSETransport,
    StdioTransport,
    StreamableHttpTransport,
)
from mcp_types.version import LATEST_HANDSHAKE_VERSION, LATEST_PROTOCOL_VERSION

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MATRIX_PATH = PROJECT_ROOT / "mcp_compat_matrix.toml"
LOCK_PATH = PROJECT_ROOT / "uv.lock"

PRIMARY_PROTOCOL = "2026-07-28"
LEGACY_SSE_PROTOCOL = "2025-11-25"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_port(host: str, port: int, timeout: float = 45.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)
    raise RuntimeError(f"server did not listen on {host}:{port} within {timeout}s")


def _assert_port_closed(host: str, port: int, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.2):
                time.sleep(0.05)
        except OSError:
            return
    raise AssertionError(f"port {host}:{port} still accepting connections after teardown")


@contextmanager
def _http_host_process(
    module: str,
    *,
    path: str,
) -> Iterator[tuple[subprocess.Popen[bytes], str, int]]:
    host = "127.0.0.1"
    port = _free_port()
    env = {
        **os.environ,
        "MCP_HOST": host,
        "MCP_PORT": str(port),
        "MCP_PATH": path,
        "MCP_CONTAINER": "demo",
        "MCP_MAX_REQUEST_BODY_BYTES": "1048576",
        "MCP_MAX_INFLIGHT_REQUESTS": "32",
        "PYTHONUNBUFFERED": "1",
    }
    if module.endswith(".sse"):
        env["MCP_TRANSPORT"] = "sse"
        env["ENTERPRISE_DATA_MCP_SSE_DEMO"] = "1"
        env["MCP_LEGACY_MAX_SESSIONS"] = "16"
        env["MCP_LEGACY_SESSION_IDLE_TIMEOUT_SECONDS"] = "300"
    elif module.endswith(".streamable_http"):
        env["MCP_TRANSPORT"] = "streamable_http"
        env["ENTERPRISE_DATA_MCP_HTTP_DEMO"] = "1"
    proc = subprocess.Popen(
        [sys.executable, "-m", module],
        cwd=str(PROJECT_ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_for_port(host, port)
        yield proc, f"http://{host}:{port}{path}", port
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)
        assert proc.poll() is not None, f"{module} process still alive after teardown"
        _assert_port_closed(host, port)


def _load_matrix() -> dict[str, object]:
    assert MATRIX_PATH.is_file(), f"missing compat matrix: {MATRIX_PATH}"
    with MATRIX_PATH.open("rb") as handle:
        return tomllib.load(handle)


def test_compat_matrix_and_lockfile_present(project_root: Path) -> None:
    assert (project_root / "mcp_compat_matrix.toml").is_file()
    assert (project_root / "uv.lock").is_file(), "uv.lock must be generated in 1-SMOKE"


def test_runtime_versions_match_locked_matrix() -> None:
    import importlib.metadata as metadata

    matrix = _load_matrix()
    runtime = matrix["runtime"]
    assert isinstance(runtime, dict)

    assert runtime["python"].startswith(f"{sys.version_info.major}.{sys.version_info.minor}.")
    assert metadata.version("fastmcp") == runtime["fastmcp"]
    assert metadata.version("mcp") == runtime["mcp"]
    assert metadata.version("mcp_types") == runtime["mcp_types"]

    lock_text = LOCK_PATH.read_text(encoding="utf-8")
    assert f'name = "fastmcp"' in lock_text
    assert f'version = "{runtime["fastmcp"]}"' in lock_text
    assert f'name = "mcp"' in lock_text
    assert f'version = "{runtime["mcp"]}"' in lock_text


def test_matrix_protocol_targets_are_not_silently_downgraded() -> None:
    matrix = _load_matrix()
    transports = matrix["transports"]
    assert isinstance(transports, dict)

    stdio = transports["stdio"]
    http = transports["streamable_http"]
    sse = transports["sse"]
    assert isinstance(stdio, dict) and isinstance(http, dict) and isinstance(sse, dict)

    assert stdio["protocol_version"] == PRIMARY_PROTOCOL == LATEST_PROTOCOL_VERSION
    assert http["protocol_version"] == PRIMARY_PROTOCOL == LATEST_PROTOCOL_VERSION
    assert sse["protocol_version"] == LEGACY_SSE_PROTOCOL == LATEST_HANDSHAKE_VERSION
    assert sse["role"] == "legacy_compat"
    assert http["path"] == "/mcp"
    assert sse["sse_path"] == "/sse"
    assert sse["message_path"] in {"/messages", "/messages/"}


def test_stdio_real_subprocess_handshake() -> None:
    async def _run() -> str:
        transport = StdioTransport(
            command=sys.executable,
            args=["-m", "enterprise_data_mcp.hosts.stdio"],
            cwd=str(PROJECT_ROOT),
            env={**os.environ},
        )
        async with Client(transport) as client:
            version = client.protocol_version
            assert version is not None
            return version

    negotiated = anyio.run(_run)
    assert negotiated == PRIMARY_PROTOCOL, (
        f"stdio silently degraded: got {negotiated!r}, want {PRIMARY_PROTOCOL!r}"
    )


def test_streamable_http_real_process_handshake() -> None:
    async def _run(url: str) -> str:
        async with Client(StreamableHttpTransport(url)) as client:
            version = client.protocol_version
            assert version is not None
            return version

    with _http_host_process(
        "enterprise_data_mcp.hosts.streamable_http",
        path="/mcp",
    ) as (proc, url, port):
        negotiated = anyio.run(_run, url)
        assert negotiated == PRIMARY_PROTOCOL, (
            f"streamable-http silently degraded: got {negotiated!r}, want {PRIMARY_PROTOCOL!r}"
        )
        assert proc.poll() is None, "HTTP host exited before handshake finished"
        _ = port


def test_legacy_sse_real_process_handshake_and_messages_route() -> None:
    async def _run(url: str, base: str) -> str:
        async with httpx2.AsyncClient() as http:
            messages = await http.get(f"{base}/messages/", timeout=3.0)
            # Route must exist (method may be limited); 404 would mean missing surface.
            assert messages.status_code != 404, "/messages route missing on legacy SSE host"
        async with Client(SSETransport(url)) as client:
            version = client.protocol_version
            assert version is not None
            return version

    with _http_host_process(
        "enterprise_data_mcp.hosts.sse",
        path="/sse",
    ) as (proc, url, port):
        base = f"http://127.0.0.1:{port}"
        negotiated = anyio.run(_run, url, base)
        assert negotiated == LEGACY_SSE_PROTOCOL, (
            f"SSE compat tier mismatch: got {negotiated!r}, want {LEGACY_SSE_PROTOCOL!r}"
        )
        assert proc.poll() is None, "SSE host exited before handshake finished"

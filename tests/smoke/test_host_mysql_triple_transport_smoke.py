"""QA-03: three Host transports must execute the SAME live MySQL query_data.

Proves real DB path (MCP_CONTAINER=mysql), not Fake/demo EMPTY results.
Checks result shape, provenance source, and SQLite audit SUCCEEDED rows.
"""

from __future__ import annotations

import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import anyio
import pytest
from fastmcp import Client
from fastmcp.client.transports import SSETransport, StdioTransport, StreamableHttpTransport

from scripts.compose_e2e import docker_bin, ensure_mysql_up, mysql_port_open

PROJECT_ROOT = Path(__file__).resolve().parents[2]

_DATASET = "sales_inventory_daily"
_TOOL = "query_data"
_PHYSICAL_SECRET = "phys_sales_secret"
_HOST = "127.0.0.1"
_ORIGIN = "http://127.0.0.1:3000"

_SAME_REQUEST: dict[str, object] = {
    "dataset_id": _DATASET,
    "projection": ["product_name"],
    "filters": [],
    "aggregations": [],
    "group_by": [],
    "order_by": [],
    "limit": 10,
}


def _extract_tool_payload(call: object) -> dict[str, Any]:
    if getattr(call, "structured_content", None) is not None:
        payload = call.structured_content
        assert isinstance(payload, dict)
        return payload
    data = getattr(call, "data", None)
    if isinstance(data, dict):
        return data
    content = getattr(call, "content", None) or []
    return json.loads(content[0].text)


def _assert_live_query_payload(payload: dict[str, Any], *, transport: str) -> dict[str, Any]:
    assert payload.get("success") is True, f"{transport}: query failed {payload!r}"
    data = payload.get("data")
    assert isinstance(data, dict), f"{transport}: missing data"
    assert data.get("result_status") == "NON_EMPTY", (
        f"{transport}: expected NON_EMPTY live MySQL rows, got {data.get('result_status')!r} "
        "(EMPTY usually means Fake/demo container)"
    )
    row_count = int(data.get("row_count") or 0)
    assert row_count > 0, f"{transport}: row_count must be > 0 for live MySQL"
    source = data.get("source")
    assert isinstance(source, dict), f"{transport}: missing provenance source"
    assert source.get("dataset_id") == _DATASET, f"{transport}: bad source.dataset_id"
    queried_at = str(source.get("queried_at_utc") or "")
    assert queried_at, f"{transport}: missing source.queried_at_utc"
    # Demo FakeClock uses fixed 1970 / 2026-09-14T00:00:00Z — live clock must differ.
    assert queried_at != "2026-09-14T00:00:00Z", (
        f"{transport}: FakeClock timestamp indicates demo container"
    )
    blob = json.dumps(payload)
    assert _PHYSICAL_SECRET not in blob
    assert "FakeQuery" not in blob
    return {
        "transport": transport,
        "row_count": row_count,
        "result_status": data.get("result_status"),
        "dataset_id": source.get("dataset_id"),
        "queried_at_utc": queried_at,
        "columns": data.get("columns"),
    }


def _assert_audit_succeeded(audit_db: Path, *, transport: str) -> dict[str, Any]:
    assert audit_db.is_file(), f"{transport}: audit db missing {audit_db}"
    conn = sqlite3.connect(str(audit_db))
    try:
        rows = conn.execute(
            "SELECT id, status, operation, dataset_id, error_code "
            "FROM audit_events WHERE operation LIKE '%query%' "
            "ORDER BY finished_at_utc DESC, created_at_utc DESC"
        ).fetchall()
        assert rows, f"{transport}: no query audit rows in {audit_db}"
        succeeded = [r for r in rows if r[1] == "SUCCEEDED"]
        assert succeeded, f"{transport}: no SUCCEEDED audit rows, got {rows!r}"
        call_id, status, operation, dataset_id, error_code = succeeded[0]
        assert dataset_id == _DATASET, f"{transport}: audit dataset_id {dataset_id!r}"
        assert error_code in (None, ""), f"{transport}: unexpected error_code {error_code!r}"
        return {
            "call_id": call_id,
            "status": status,
            "operation": operation,
            "dataset_id": dataset_id,
        }
    finally:
        conn.close()


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind((_HOST, 0))
        return int(sock.getsockname()[1])


def _wait_for_port(port: int, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((_HOST, port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)
    raise RuntimeError(f"host did not listen on {_HOST}:{port}")


def _mysql_host_env(extra: dict[str, str], *, audit_db: Path) -> dict[str, str]:
    return {
        **os.environ,
        "MCP_CONTAINER": "mysql",
        "MCP_POLICY_PROFILE": "demo_readonly",
        "MYSQL_HOST": os.environ.get("MYSQL_HOST", "127.0.0.1"),
        "MYSQL_PORT": os.environ.get("MYSQL_PORT", "3307"),
        "MYSQL_USER": os.environ.get("MYSQL_USER", "edmcp_ro"),
        "MYSQL_PASSWORD": os.environ.get("MYSQL_PASSWORD", "demoro"),
        "MYSQL_DATABASE": os.environ.get("MYSQL_DATABASE", "edmcp_demo"),
        "AUDIT_DB_PATH": str(audit_db),
        "PYTHONUNBUFFERED": "1",
        **extra,
    }


@contextmanager
def _http_like_process(
    *,
    module: str,
    transport: str,
    path: str,
    audit_db: Path,
) -> Iterator[tuple[subprocess.Popen[bytes], int, str]]:
    port = _free_port()
    env = _mysql_host_env(
        {
            "MCP_TRANSPORT": transport,
            "MCP_HOST": _HOST,
            "MCP_PORT": str(port),
            "MCP_PATH": path,
            "MCP_ALLOWED_ORIGINS": _ORIGIN,
            "MCP_MAX_REQUEST_BODY_BYTES": "1048576",
            "MCP_MAX_INFLIGHT_REQUESTS": "32",
            "MCP_CALLER_ID": f"qa03-{transport}-client",
            "MCP_LEGACY_MAX_SESSIONS": "16",
            "MCP_LEGACY_SESSION_IDLE_TIMEOUT_SECONDS": "300",
        },
        audit_db=audit_db,
    )
    proc = subprocess.Popen(
        [sys.executable, "-u", "-m", module],
        cwd=str(PROJECT_ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_for_port(port)
        yield proc, port, f"http://{_HOST}:{port}{path}"
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=3)


@pytest.fixture(scope="module")
def live_mysql() -> Iterator[None]:
    if docker_bin() is None:
        pytest.fail("docker binary not found — QA-03 requires live MySQL")
    owned = False
    try:
        owned = ensure_mysql_up(timeout_s=120.0)
        deadline = time.monotonic() + 90.0
        while time.monotonic() < deadline and not mysql_port_open():
            time.sleep(0.5)
        assert mysql_port_open(), "MySQL 127.0.0.1:3307 not reachable"
        # brief settle for ready queries
        time.sleep(2.0)
        yield
    finally:
        # Do not tear down shared MySQL if we didn't start it; if we started it,
        # leave it up for subsequent QA cards (compose_down is optional).
        _ = owned


@pytest.mark.timeout(180)
def test_three_transports_same_live_mysql_query_audit_and_source(
    live_mysql: None, tmp_path: Path
) -> None:
    """stdio + Streamable HTTP + SSE: identical request → live rows + audit + source."""
    summaries: list[dict[str, Any]] = []

    # --- stdio ---
    audit_stdio = tmp_path / "audit-stdio.sqlite3"
    stdio_env = _mysql_host_env(
        {
            "MCP_TRANSPORT": "stdio",
            "MCP_CALLER_ID": "qa03-stdio-client",
        },
        audit_db=audit_stdio,
    )

    async def _stdio() -> dict[str, Any]:
        transport = StdioTransport(
            command=sys.executable,
            args=["-m", "enterprise_data_mcp.hosts.stdio"],
            cwd=str(PROJECT_ROOT),
            env=stdio_env,
        )
        async with Client(transport) as client:
            call = await client.call_tool(_TOOL, {"request": _SAME_REQUEST})
            return _extract_tool_payload(call)

    stdio_payload = anyio.run(_stdio)
    stdio_summary = _assert_live_query_payload(stdio_payload, transport="stdio")
    stdio_audit = _assert_audit_succeeded(audit_stdio, transport="stdio")
    summaries.append({**stdio_summary, "audit": stdio_audit})

    # --- streamable HTTP ---
    audit_http = tmp_path / "audit-http.sqlite3"
    with _http_like_process(
        module="enterprise_data_mcp.hosts.streamable_http",
        transport="streamable_http",
        path="/mcp",
        audit_db=audit_http,
    ) as (proc, _port, mcp_url):
        assert proc.poll() is None

        async def _http() -> dict[str, Any]:
            async with Client(StreamableHttpTransport(mcp_url)) as client:
                call = await client.call_tool(_TOOL, {"request": _SAME_REQUEST})
                return _extract_tool_payload(call)

        http_payload = anyio.run(_http)
    http_summary = _assert_live_query_payload(http_payload, transport="streamable_http")
    http_audit = _assert_audit_succeeded(audit_http, transport="streamable_http")
    summaries.append({**http_summary, "audit": http_audit})

    # --- SSE ---
    audit_sse = tmp_path / "audit-sse.sqlite3"
    with _http_like_process(
        module="enterprise_data_mcp.hosts.sse",
        transport="sse",
        path="/sse",
        audit_db=audit_sse,
    ) as (proc, _port, sse_url):
        assert proc.poll() is None

        async def _sse() -> dict[str, Any]:
            async with Client(SSETransport(sse_url)) as client:
                call = await client.call_tool(_TOOL, {"request": _SAME_REQUEST})
                return _extract_tool_payload(call)

        sse_payload = anyio.run(_sse)
    sse_summary = _assert_live_query_payload(sse_payload, transport="sse")
    sse_audit = _assert_audit_succeeded(audit_sse, transport="sse")
    summaries.append({**sse_summary, "audit": sse_audit})

    # Same query contract across transports
    row_counts = {s["row_count"] for s in summaries}
    assert len(row_counts) == 1, f"row_count must match across transports: {summaries!r}"
    datasets = {s["dataset_id"] for s in summaries}
    assert datasets == {_DATASET}

    # Evidence for the QA card (printed in pytest capture)
    print("QA03_TRIPLE_TRANSPORT_EVIDENCE", json.dumps(summaries, ensure_ascii=False))

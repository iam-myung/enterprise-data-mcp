"""Step 10 SMOKE: real stdio Host subprocess (SPEC §18.4 / API §2).

list/read/call · graceful exit · stdout free of log pollution.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import anyio
from fastmcp import Client
from fastmcp.client.transports import StdioTransport

PROJECT_ROOT = Path(__file__).resolve().parents[2]

_DATASETS_URI = "enterprise-data://datasets"
_TOOL_NAME = "query_data"
_DATASET = "sales_inventory_daily"
_PHYSICAL = "phys_sales_secret"
_CALLER_ID = "demo-stdio-client"
_POLICY_PROFILE = "demo_readonly"
_PRIMARY_PROTOCOL = "2026-07-28"

_HOST_ENV = {
    "MCP_CALLER_ID": _CALLER_ID,
    "MCP_POLICY_PROFILE": _POLICY_PROFILE,
    "MCP_TRANSPORT": "stdio",
    "ENTERPRISE_DATA_MCP_STDIO_DEMO": "1",
    "PYTHONUNBUFFERED": "1",
}


def _host_env() -> dict[str, str]:
    return {**os.environ, **_HOST_ENV}


def test_stdio_host_startup_log_on_stderr_stdout_clean() -> None:
    """Before any MCP frames: stderr may log JSON; stdout must stay empty."""
    proc = subprocess.Popen(
        [sys.executable, "-u", "-m", "enterprise_data_mcp.hosts.stdio"],
        cwd=str(PROJECT_ROOT),
        env=_host_env(),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        # Host emits structured log then blocks on stdio transport.
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                break
            # Give interpreter + emit_host_log time under pytest load.
            time.sleep(0.25)
            if time.monotonic() >= deadline - 13.0:
                # After ~2s assume startup log flushed (PYTHONUNBUFFERED / -u).
                break

        assert proc.poll() is None, "stdio host exited before smoke probe"

        proc.terminate()
        try:
            stdout, stderr = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate(timeout=2)

        assert proc.returncode is not None, "host process still alive after teardown"
        out_text = stdout.decode("utf-8", errors="replace")
        err_text = stderr.decode("utf-8", errors="replace")

        # stdout: no structured host log / no banner pollution
        assert "stdio.host.start" not in out_text
        assert '"event"' not in out_text
        assert "Starting MCP server" not in out_text
        assert out_text.strip() == "", f"stdout polluted before MCP I/O: {out_text!r}"

        # stderr: host structured log present
        assert "stdio.host.start" in err_text, f"missing host log on stderr: {err_text!r}"
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=2)


def test_stdio_host_real_subprocess_list_read_call_and_exit() -> None:
    """Real Client over stdio: handshake + list/read/call; session end cleans up."""

    async def _run() -> dict[str, Any]:
        transport = StdioTransport(
            command=sys.executable,
            args=["-m", "enterprise_data_mcp.hosts.stdio"],
            cwd=str(PROJECT_ROOT),
            env=_host_env(),
        )
        async with Client(transport) as client:
            version = client.protocol_version
            resources = await client.list_resources()
            uris = {str(r.uri) for r in resources}
            listed = await client.read_resource(_DATASETS_URI)
            tools = await client.list_tools()
            names = {t.name for t in tools}
            call = await client.call_tool(
                _TOOL_NAME,
                {
                    "request": {
                        "dataset_id": _DATASET,
                        "projection": ["product_name"],
                        "filters": [],
                        "aggregations": [],
                        "group_by": [],
                        "order_by": [],
                        "limit": 10,
                    }
                },
            )
            return {
                "version": version,
                "uris": uris,
                "listed": listed,
                "names": names,
                "call": call,
            }

    out = anyio.run(_run)

    assert out["version"] == _PRIMARY_PROTOCOL
    assert _DATASETS_URI in out["uris"]
    assert _TOOL_NAME in out["names"]
    assert "execute_sql" not in out["names"]

    listed = out["listed"]
    listed_raw = listed[0].text if isinstance(listed, list) else listed.contents[0].content
    listed_payload = json.loads(listed_raw)
    assert listed_payload["success"] is True
    assert _PHYSICAL not in listed_raw

    call = out["call"]
    if getattr(call, "structured_content", None) is not None:
        payload = call.structured_content
    else:
        data = getattr(call, "data", None)
        if isinstance(data, dict):
            payload = data
        else:
            content = getattr(call, "content", None) or []
            payload = json.loads(content[0].text)
    assert payload["success"] is True
    assert payload["data"]["result_status"] == "EMPTY"
    assert _PHYSICAL not in json.dumps(payload)

    # No hanging host: a second short startup/teardown must succeed quickly.
    probe = subprocess.Popen(
        [sys.executable, "-m", "enterprise_data_mcp.hosts.stdio"],
        cwd=str(PROJECT_ROOT),
        env=_host_env(),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        time.sleep(0.3)
        assert probe.poll() is None
        probe.terminate()
        probe.wait(timeout=5)
    finally:
        if probe.poll() is None:
            probe.kill()
            probe.wait(timeout=2)
    assert probe.poll() is not None

"""Docker Compose headless E2E helper (SPEC §15 / Step 14 SMOKE)."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = PROJECT_ROOT / "docker" / "compose.yaml"
MYSQL_HOST = "127.0.0.1"
MYSQL_PORT = 3307


def docker_bin() -> str | None:
    return shutil.which("docker")


def compose_base_cmd() -> list[str]:
    exe = docker_bin()
    if not exe:
        raise RuntimeError("docker binary not found on PATH")
    return [exe, "compose", "-f", str(COMPOSE_FILE)]


def compose_up(
    *, timeout_s: float = 120.0, services: Sequence[str] | None = None
) -> None:
    last_err: BaseException | None = None
    service_args = list(services) if services else []
    for attempt in range(3):
        try:
            subprocess.run(
                compose_base_cmd() + ["up", "-d", "--wait", *service_args],
                cwd=str(PROJECT_ROOT),
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
            if mysql_port_open():
                return
        except subprocess.CalledProcessError as exc:
            last_err = exc
            try:
                subprocess.run(
                    compose_base_cmd() + ["up", "-d", *service_args],
                    cwd=str(PROJECT_ROOT),
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                _wait_port(MYSQL_HOST, MYSQL_PORT, timeout_s=timeout_s)
                return
            except (subprocess.CalledProcessError, TimeoutError) as inner:
                last_err = inner
        time.sleep(2.0 * (attempt + 1))
    if last_err is not None:
        raise last_err
    raise RuntimeError("compose_up failed without captured error")


def compose_down() -> None:
    subprocess.run(
        compose_base_cmd() + ["down", "--remove-orphans"],
        cwd=str(PROJECT_ROOT),
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def mysql_port_open(host: str = MYSQL_HOST, port: int = MYSQL_PORT) -> bool:
    import socket

    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def _wait_port(host: str, port: int, *, timeout_s: float) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if mysql_port_open(host, port):
            return
        time.sleep(0.5)
    raise TimeoutError(f"MySQL port {host}:{port} not open within {timeout_s}s")


def ensure_mysql_up(*, timeout_s: float = 120.0) -> bool:
    """Ensure compose MySQL is reachable. Returns True if this call started it."""
    if mysql_port_open():
        return False
    # Only start mysql — waiting on the full stack is flaky for GQ/perf gates.
    compose_up(timeout_s=timeout_s, services=("mysql",))
    return True


def probe_mysql_select1() -> dict[str, Any]:
    """Real DB round-trip against compose demo credentials."""
    import mysql.connector

    conn = mysql.connector.connect(
        host=os.environ.get("MYSQL_HOST", MYSQL_HOST),
        port=int(os.environ.get("MYSQL_PORT", str(MYSQL_PORT))),
        user=os.environ.get("MYSQL_USER", "edmcp_ro"),
        password=os.environ.get("MYSQL_PASSWORD", "demoro"),
        database=os.environ.get("MYSQL_DATABASE", "edmcp_demo"),
        connection_timeout=5,
    )
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1")
        row = cur.fetchone()
        cur.close()
        ok = row is not None and int(row[0]) == 1
        return {"ok": ok, "row": row}
    finally:
        conn.close()


def probe_execute_read_query() -> dict[str, Any]:
    """Application-layer query against live MySQL (not FakeQuery)."""
    from enterprise_data_mcp.bootstrap.container import build_mysql_container
    from enterprise_data_mcp.bootstrap.settings import load_stdio_settings

    settings = load_stdio_settings(
        {
            "MCP_CALLER_ID": "compose-e2e-client",
            "MCP_POLICY_PROFILE": "demo_readonly",
            "MCP_TRANSPORT": "stdio",
        }
    )
    container = build_mysql_container(settings)
    envelope = container.execute_query.execute(
        caller=container.caller,
        call_id=f"compose-e2e-query-{uuid.uuid4().hex[:12]}",
        request={
            "dataset_id": "sales_inventory_daily",
            "projection": ["product_name"],
            "filters": [],
            "aggregations": [],
            "group_by": [],
            "order_by": [],
            "limit": 10,
        },
    )
    row_count = 0 if envelope.data is None else int(envelope.data.row_count)
    return {
        "ok": bool(envelope.success) and row_count > 0,
        "success": bool(envelope.success),
        "row_count": row_count,
        "error": None if envelope.error is None else str(envelope.error),
    }


def run_full_e2e() -> dict[str, Any]:
    """Compose up → SELECT 1 → ExecuteReadQuery → Compose down (if owned)."""
    if docker_bin() is None:
        return {
            "ok": False,
            "reason": "docker binary not found on PATH",
            "cleaned_up": True,
        }
    if not COMPOSE_FILE.is_file():
        return {
            "ok": False,
            "reason": f"missing compose file: {COMPOSE_FILE}",
            "cleaned_up": True,
        }

    owned = False
    probe: dict[str, Any] | None = None
    query_probe: dict[str, Any] | None = None
    error: str | None = None
    try:
        owned = ensure_mysql_up()
        probe = probe_mysql_select1()
        if not probe.get("ok"):
            error = f"mysql probe failed: {probe!r}"
        else:
            query_probe = probe_execute_read_query()
            if not query_probe.get("ok"):
                error = f"execute_read_query probe failed: {query_probe!r}"
    except Exception as exc:  # noqa: BLE001 — report to smoke
        error = str(exc)
    finally:
        cleaned_up = True
        if owned:
            try:
                compose_down()
            except Exception as down_exc:  # noqa: BLE001
                error = (
                    f"{error}; down failed: {down_exc}"
                    if error
                    else f"down failed: {down_exc}"
                )
                cleaned_up = False
            # Restore MySQL so later tests in the same pytest session are not starved.
            try:
                ensure_mysql_up(timeout_s=120.0)
            except Exception:  # noqa: BLE001 — best-effort suite continuity
                pass

    if error:
        return {
            "ok": False,
            "reason": error,
            "probe": probe,
            "query_probe": query_probe,
            "cleaned_up": cleaned_up,
        }
    return {
        "ok": True,
        "reason": "compose e2e ok",
        "probe": probe,
        "query_probe": query_probe,
        "cleaned_up": cleaned_up,
    }

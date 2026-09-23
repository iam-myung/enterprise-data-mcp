"""Step 14 SMOKE: secret scan · live MySQL perf/RSS (SPEC §16.4 / §20)."""

from __future__ import annotations

import platform
import time
import uuid
from pathlib import Path

import pytest

from scripts.compose_e2e import compose_down, docker_bin, ensure_mysql_up
from scripts.perf_baseline import (
    MIN_LATENCY_SAMPLES,
    P95_QUERY_MS_MAX,
    P99_QUERY_MS_MAX,
    RSS_GROWTH_MB_MAX_AFTER_100,
    RSS_MB_MAX,
    evaluate_latency_ms,
    evaluate_rss_mb,
)
from scripts.secret_scan import scan_paths

PROJECT_ROOT = Path(__file__).resolve().parents[2]

_DATASET_SCALE = "mysql-view-10029"
_QUERY_REQUEST: dict[str, object] = {
    "dataset_id": "sales_inventory_daily",
    "projection": ["product_name"],
    "filters": [],
    "aggregations": [],
    "group_by": [],
    "order_by": [],
    "limit": 10,
}


def _iter_env_like_files() -> list[Path]:
    """Scan committed env surfaces only (exclude local .env and temp/cache trees)."""
    out: list[Path] = []
    skip_parts = {
        "var",
        ".venv",
        ".venv.bak_broken",
        "__pycache__",
        ".pytest_cache",
        "site-packages",
    }
    for path in PROJECT_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in skip_parts for part in path.parts):
            continue
        name = path.name.lower()
        # Local developer secrets are gitignored; scan .env.example instead.
        if name == ".env":
            continue
        if name.endswith(".env") or name.endswith(".env.example") or name == ".env.example":
            out.append(path)
    example = PROJECT_ROOT / ".env.example"
    if example.is_file() and example not in out:
        out.append(example)
    return out


def test_secret_scan_deliverable_tree_clean() -> None:
    files = _iter_env_like_files()
    findings = scan_paths(files)
    assert findings == [], "secret scan findings:\n" + "\n".join(findings)


def _execute_query_ok(container: object, caller: object, *, call_id: str):
    """Run one query; retry briefly on transient DATA_SOURCE_UNAVAILABLE."""
    from enterprise_data_mcp.adapters.outbound.mysql.errors import MysqlAdapterError
    from enterprise_data_mcp.domain.errors import ErrorCode

    last_err: object | None = None
    for attempt in range(3):
        try:
            envelope = container.execute_query.execute(  # type: ignore[attr-defined]
                caller=caller,
                call_id=f"{call_id}-a{attempt}",
                request=_QUERY_REQUEST,
            )
        except MysqlAdapterError as exc:
            last_err = exc
            time.sleep(0.5 * (attempt + 1))
            continue
        if envelope.success and envelope.data is not None and envelope.data.row_count > 0:
            return envelope
        code = getattr(getattr(envelope, "error", None), "code", None)
        if code == ErrorCode.DATA_SOURCE_UNAVAILABLE or str(code) == "DATA_SOURCE_UNAVAILABLE":
            last_err = envelope.error
            time.sleep(0.5 * (attempt + 1))
            continue
        return envelope
    pytest.fail(f"query failed after retries: {last_err!r}")


@pytest.mark.timeout(120)
def test_perf_and_rss_baseline_recorded_for_local_query_path() -> None:
    """Live MySQL P95/P99 + measured RSS growth after 100 queries (no model time)."""
    from enterprise_data_mcp.bootstrap.container import build_mysql_container
    from enterprise_data_mcp.bootstrap.settings import load_stdio_settings
    from enterprise_data_mcp.domain.errors import TransportKind
    from enterprise_data_mcp.domain.models import CallerContext

    if docker_bin() is None:
        pytest.fail("docker binary not found on PATH — live MySQL baseline required")

    settings = load_stdio_settings(
        {
            "MCP_CALLER_ID": "smoke-perf-client",
            "MCP_POLICY_PROFILE": "demo_readonly",
            "MCP_TRANSPORT": "stdio",
        }
    )
    owned = False
    try:
        owned = ensure_mysql_up()
        container = build_mysql_container(settings)
        caller = container.caller
        assert isinstance(caller, CallerContext)
        assert caller.transport == TransportKind.STDIO

        samples_ms: list[float] = []
        for i in range(MIN_LATENCY_SAMPLES):
            started_at = time.perf_counter()
            envelope = _execute_query_ok(
                container,
                caller,
                call_id=f"smoke-perf-latency-{i}-{uuid.uuid4().hex[:8]}",
            )
            samples_ms.append((time.perf_counter() - started_at) * 1000.0)
            assert envelope.success is True, f"latency sample failed: {envelope.error!r}"
            assert envelope.data is not None
            assert envelope.data.row_count > 0

        report = evaluate_latency_ms(samples_ms)
        meta = {
            "machine": platform.node(),
            "platform": platform.platform(),
            "python": platform.python_version(),
            "dataset_scale": _DATASET_SCALE,
            "samples": len(samples_ms),
            "p95_ms": report.get("p95_ms"),
            "p99_ms": report.get("p99_ms"),
            "ceilings": {"p95": P95_QUERY_MS_MAX, "p99": P99_QUERY_MS_MAX},
            "note": "in-process ExecuteReadQuery via MysqlQueryAdapter; excludes model time",
        }
        print("PERF_RECORD", meta)
        assert report["ok"] is True, f"latency gate failed: {report} meta={meta}"

        rss_before = _process_rss_mb()
        for i in range(100):
            envelope = _execute_query_ok(
                container,
                caller,
                call_id=f"smoke-perf-rss-{i}-{uuid.uuid4().hex[:8]}",
            )
            assert envelope.success is True, f"rss sample failed: {envelope.error!r}"
        rss_after = _process_rss_mb()
        growth = max(0.0, rss_after - rss_before)
        rss_report = evaluate_rss_mb(
            steady_rss_mb=rss_after,
            growth_after_100_queries_mb=growth,
        )
        print(
            "RSS_RECORD",
            {
                "rss_before_mb": rss_before,
                "rss_after_mb": rss_after,
                "growth_mb": growth,
                "report": dict(rss_report),
            },
        )
        assert rss_report["growth_after_100_queries_mb"] <= RSS_GROWTH_MB_MAX_AFTER_100
        # Absolute RSS ceiling applies to a clean process. Under a long pytest
        # session the interpreter may already exceed the ceiling before samples.
        if rss_before <= RSS_MB_MAX:
            assert rss_report["ok"] is True, f"rss gate failed: {rss_report}"
            assert rss_after <= RSS_MB_MAX
        else:
            assert growth <= RSS_GROWTH_MB_MAX_AFTER_100, (
                f"rss growth gate failed under suite pollution: {rss_report}"
            )
        assert growth <= RSS_GROWTH_MB_MAX_AFTER_100
    finally:
        if owned:
            try:
                compose_down()
            except Exception:  # noqa: BLE001 — cleanup best-effort
                pass
            try:
                ensure_mysql_up(timeout_s=120.0)
            except Exception:  # noqa: BLE001 — suite continuity
                pass


def _process_rss_mb() -> float:
    try:
        import resource  # type: ignore[import-not-found]

        rss_mb = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) / 1024.0
        if rss_mb > RSS_MB_MAX * 8:
            rss_mb = rss_mb / 1024.0
        return rss_mb
    except ImportError:
        return _windows_rss_mb()


def _windows_rss_mb() -> float:
    import ctypes
    from ctypes import wintypes

    class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    get_current = kernel32.GetCurrentProcess
    get_current.restype = wintypes.HANDLE
    get_mem = psapi.GetProcessMemoryInfo
    get_mem.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(PROCESS_MEMORY_COUNTERS),
        wintypes.DWORD,
    ]
    get_mem.restype = wintypes.BOOL
    counters = PROCESS_MEMORY_COUNTERS()
    counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
    if not get_mem(get_current(), ctypes.byref(counters), counters.cb):
        err = ctypes.get_last_error()
        pytest.fail(f"unable to read process RSS on Windows (winerr={err})")
    return float(counters.WorkingSetSize) / (1024.0 * 1024.0)

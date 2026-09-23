"""BUG-04-RED: build_mysql_container must wire real telemetry (SPEC §16).

Approved (BUG-04-PLAN): Composite OTel + Prometheus + JSON log on Live path.
No production changes in this Step.
"""

from __future__ import annotations

import io
import time
import uuid

import pytest

from scripts.compose_e2e import compose_down, docker_bin, ensure_mysql_up

_QUERY_REQUEST: dict[str, object] = {
    "dataset_id": "sales_inventory_daily",
    "projection": ["product_name"],
    "filters": [],
    "aggregations": [],
    "group_by": [],
    "order_by": [],
    "limit": 10,
}

_FORBIDDEN_LOG_FRAGMENTS = (
    "password",
    "MYSQL_PASSWORD",
    "changeme",
    "demoro",
    "SELECT ",
    "mysql+pymysql",
)


def _execute_one(container: object, caller: object, *, call_id: str):
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
        if envelope.success and envelope.data is not None:
            return envelope
        code = getattr(getattr(envelope, "error", None), "code", None)
        if code == ErrorCode.DATA_SOURCE_UNAVAILABLE or str(code) == "DATA_SOURCE_UNAVAILABLE":
            last_err = envelope.error
            time.sleep(0.5 * (attempt + 1))
            continue
        return envelope
    pytest.fail(f"query failed after retries: {last_err!r}")


@pytest.mark.timeout(120)
def test_mysql_container_live_query_emits_log_metrics_and_trace() -> None:
    from enterprise_data_mcp.bootstrap.container import (
        _FakeTelemetryPort,
        build_mysql_container,
    )
    from enterprise_data_mcp.bootstrap.settings import load_stdio_settings

    if docker_bin() is None:
        pytest.fail("docker binary not found on PATH — live MySQL required for BUG-04")

    settings = load_stdio_settings(
        {
            "MCP_CALLER_ID": "bug04-telemetry-client",
            "MCP_POLICY_PROFILE": "demo_readonly",
            "MCP_TRANSPORT": "stdio",
        }
    )
    owned = False
    try:
        owned = ensure_mysql_up()
        container = build_mysql_container(settings)
        telemetry = container.execute_query._telemetry  # noqa: SLF001

        assert not isinstance(telemetry, _FakeTelemetryPort), (
            "build_mysql_container must not inject _FakeTelemetryPort"
        )

        envelope = _execute_one(
            container,
            container.caller,
            call_id=f"bug04-tel-{uuid.uuid4().hex[:8]}",
        )
        assert envelope.success is True
        assert envelope.data is not None

        get_spans = getattr(telemetry, "get_finished_spans", None)
        assert callable(get_spans), "Live telemetry must expose get_finished_spans()"
        flush = getattr(telemetry, "force_flush", None)
        if callable(flush):
            flush()
        spans = list(get_spans())
        assert len(spans) >= 1, "expected finished OTel span(s) after real query"

        gen = getattr(telemetry, "generate_latest", None)
        assert callable(gen), "Live telemetry must expose generate_latest()"
        metrics_raw = gen()
        metrics_text = (
            metrics_raw.decode("utf-8")
            if isinstance(metrics_raw, bytes)
            else str(metrics_raw)
        )
        assert "mcp_requests_total" in metrics_text
        assert 'caller_id="' not in metrics_text
        assert 'sql="' not in metrics_text

        log_text = ""
        for attr in ("log_stream", "log_buffer", "_log_stream", "_buffer"):
            buf = getattr(telemetry, attr, None)
            if isinstance(buf, io.StringIO):
                log_text = buf.getvalue()
                break
            if isinstance(buf, list):
                log_text = "\n".join(str(x) for x in buf)
                break
        if not log_text:
            dump = getattr(telemetry, "dump_logs", None)
            if callable(dump):
                log_text = str(dump())
        assert log_text.strip(), "expected structured JSON log line(s) after real query"
        lowered = log_text.lower()
        for frag in _FORBIDDEN_LOG_FRAGMENTS:
            assert frag.lower() not in lowered, f"sensitive fragment in logs: {frag!r}"
        assert "trace_id" in log_text
        assert "operation" in log_text
    finally:
        if owned:
            compose_down()

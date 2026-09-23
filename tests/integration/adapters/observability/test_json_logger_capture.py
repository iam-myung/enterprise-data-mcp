"""RED: real capture of one redacted JSON log line (SPEC §16.1 / Step 8.1).

No production StructuredJsonLogger until 8.1-GREEN.
"""

from __future__ import annotations

import json
from io import StringIO
from typing import Any


def _logger() -> Any:
    from enterprise_data_mcp.adapters.observability.json_logger import (
        StructuredJsonLogger,
    )

    return StructuredJsonLogger()


def test_real_stream_captures_one_redacted_json_event() -> None:
    logger = _logger()
    stream = StringIO()
    logger.emit(
        stream=stream,
        level="INFO",
        event="mcp.request",
        trace_id="smoke-tr-1",
        operation="query_data",
        status="SUCCEEDED",
        duration_ms=42,
        timestamp_utc="2026-09-14T00:10:00Z",
        dataset_id="sales_inventory_daily",
        password="must-not-appear",
        sql="SELECT secret FROM t",
    )
    raw = stream.getvalue()
    assert raw.strip(), "expected captured log output"
    # One JSON object per line (trailing newline optional).
    lines = [ln for ln in raw.splitlines() if ln.strip()]
    assert len(lines) >= 1
    payload = json.loads(lines[0])
    for key in (
        "timestamp_utc",
        "level",
        "event",
        "trace_id",
        "operation",
        "status",
        "duration_ms",
    ):
        assert key in payload
    assert payload["dataset_id"] == "sales_inventory_daily"
    blob = raw.lower()
    assert "password" not in blob
    assert "must-not-appear" not in blob
    assert "select secret" not in blob
    assert "sql" not in payload

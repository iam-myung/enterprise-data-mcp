"""RED: whitelist-redacted structured JSON logger (SPEC §16.1 / Step 8.1).

Core field closure; unknown keys dropped; secrets/SQL/PII must not appear.
No production logger until 8.1-GREEN.
"""

from __future__ import annotations

import json
from io import StringIO
from typing import Any

import pytest

_CORE_FIELDS: frozenset[str] = frozenset(
    {
        "timestamp_utc",
        "level",
        "event",
        "trace_id",
        "operation",
        "status",
        "duration_ms",
    }
)

_ALLOWED_EXTRA: frozenset[str] = frozenset(
    {
        "dataset_id",
        "error_code",
        "row_count",
        "transport",
        "audit_stage",
    }
)

_FORBIDDEN_TOKENS: frozenset[str] = frozenset(
    {
        "password",
        "secret",
        "sql",
        "raw_sql",
        "query_values",
        "connection_string",
        "/users/admin",
        "alice@example.com",
    }
)

_LEVELS: frozenset[str] = frozenset({"DEBUG", "INFO", "WARN", "ERROR"})


def _logger_cls() -> Any:
    from enterprise_data_mcp.adapters.observability.json_logger import (
        StructuredJsonLogger,
    )

    return StructuredJsonLogger


def _emit_and_parse(logger: Any, **kwargs: Any) -> dict[str, Any]:
    stream = StringIO()
    logger.emit(stream=stream, **kwargs)
    line = stream.getvalue().strip()
    assert line, "expected one JSON log line"
    payload = json.loads(line)
    assert isinstance(payload, dict)
    return payload


def test_structured_json_logger_importable() -> None:
    cls = _logger_cls()
    assert callable(getattr(cls, "emit", None)) or hasattr(cls, "emit")


def test_emit_includes_core_field_closure() -> None:
    logger = _logger_cls()()
    payload = _emit_and_parse(
        logger,
        level="INFO",
        event="mcp.request",
        trace_id="tr-1",
        operation="query_data",
        status="SUCCEEDED",
        duration_ms=12,
        timestamp_utc="2026-09-14T00:00:00Z",
    )
    assert _CORE_FIELDS.issubset(payload.keys())
    assert payload["level"] in _LEVELS
    assert payload["event"] == "mcp.request"
    assert payload["trace_id"] == "tr-1"
    assert payload["operation"] == "query_data"
    assert payload["status"] == "SUCCEEDED"
    assert payload["duration_ms"] == 12
    assert payload["timestamp_utc"] == "2026-09-14T00:00:00Z"


def test_allowed_extra_fields_pass_whitelist() -> None:
    logger = _logger_cls()()
    payload = _emit_and_parse(
        logger,
        level="INFO",
        event="audit.write",
        trace_id="tr-2",
        operation="finish",
        status="FAILED",
        duration_ms=3,
        timestamp_utc="2026-09-14T00:00:01Z",
        dataset_id="sales_inventory_daily",
        error_code="AUDIT_UNAVAILABLE",
        row_count=0,
        transport="STDIO",
        audit_stage="finish",
    )
    for key in _ALLOWED_EXTRA:
        assert key in payload


def test_unknown_keys_are_dropped() -> None:
    logger = _logger_cls()()
    payload = _emit_and_parse(
        logger,
        level="INFO",
        event="policy.check",
        trace_id="tr-3",
        operation="list_datasets",
        status="SUCCEEDED",
        duration_ms=1,
        timestamp_utc="2026-09-14T00:00:02Z",
        not_on_whitelist="should-vanish",
        internal_debug_blob={"x": 1},
    )
    assert "not_on_whitelist" not in payload
    assert "internal_debug_blob" not in payload
    assert _CORE_FIELDS.issubset(payload.keys())


def test_forbidden_secret_and_sql_keys_never_emitted() -> None:
    logger = _logger_cls()()
    payload = _emit_and_parse(
        logger,
        level="ERROR",
        event="mysql.execute",
        trace_id="tr-4",
        operation="query_data",
        status="FAILED",
        duration_ms=9,
        timestamp_utc="2026-09-14T00:00:03Z",
        password="s3cret",
        sql="SELECT * FROM users",
        raw_sql="SELECT 1",
        query_values={"a": 1},
        secret="tok",
        connection_string="mysql://u:p@h/db",
    )
    # Key names must be absent; do not bare-substring-scan "sql" against the
    # whole blob — legitimate event "mysql.execute" (SPEC §16.2) contains it.
    for key in (
        "password",
        "secret",
        "sql",
        "raw_sql",
        "query_values",
        "connection_string",
    ):
        assert key not in payload
    blob = json.dumps(payload, ensure_ascii=False).lower()
    for value_token in (
        "s3cret",
        "select * from users",
        "mysql://",
        "select 1",
        "tok",
    ):
        assert value_token not in blob
    assert payload.get("event") == "mysql.execute"


def test_forbidden_pii_and_path_values_not_in_output() -> None:
    logger = _logger_cls()()
    # Even if slipped via a would-be allowed key, values must not leak PII/paths
    # when the implementation redacts; unknown key with PII must be dropped.
    payload = _emit_and_parse(
        logger,
        level="WARN",
        event="catalog.read",
        trace_id="tr-5",
        operation="get_schema",
        status="REJECTED",
        duration_ms=2,
        timestamp_utc="2026-09-14T00:00:04Z",
        email="alice@example.com",
        home_path="/users/admin",
    )
    blob = json.dumps(payload, ensure_ascii=False).lower()
    assert "alice@example.com" not in blob
    assert "/users/admin" not in blob
    assert "email" not in payload
    assert "home_path" not in payload


@pytest.mark.parametrize("level", sorted(_LEVELS))
def test_level_enum_accepted(level: str) -> None:
    logger = _logger_cls()()
    payload = _emit_and_parse(
        logger,
        level=level,
        event="mcp.request",
        trace_id="tr-lvl",
        operation="ping",
        status="SUCCEEDED",
        duration_ms=0,
        timestamp_utc="2026-09-14T00:00:05Z",
    )
    assert payload["level"] == level

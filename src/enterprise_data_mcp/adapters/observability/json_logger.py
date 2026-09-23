"""Whitelist-redacted structured JSON logger (SPEC §16.1 / Step 8.1).

Core field closure + event-level extras only. No Trace/Metrics/Host.
"""

from __future__ import annotations

import json
from typing import Any, TextIO

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

_ALLOWED_KEYS: frozenset[str] = _CORE_FIELDS | _ALLOWED_EXTRA


class StructuredJsonLogger:
    """Emit one JSON log line per call; unknown / forbidden keys are dropped."""

    def emit(self, *, stream: TextIO, **kwargs: Any) -> None:
        payload: dict[str, Any] = {
            key: kwargs[key] for key in _ALLOWED_KEYS if key in kwargs
        }
        stream.write(json.dumps(payload, ensure_ascii=False) + "\n")
        stream.flush()

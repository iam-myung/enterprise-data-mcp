"""stdio transport host — business MCP surface; stdout protocol / stderr logs."""

from __future__ import annotations

import os
import sys
from typing import Any, TextIO

from enterprise_data_mcp.adapters.inbound.mcp.envelope_codec import (
    envelope_to_jsonable,
)
from enterprise_data_mcp.adapters.observability.json_logger import (
    StructuredJsonLogger,
)
from enterprise_data_mcp.bootstrap.container import resolve_app_container
from enterprise_data_mcp.bootstrap.settings import load_stdio_settings
from enterprise_data_mcp.domain.errors import ErrorCode
from enterprise_data_mcp.domain.models import EnvelopeMeta, ErrorInfo, OperationEnvelope
from enterprise_data_mcp.hosts import build_stdio_server

_logger = StructuredJsonLogger()


def emit_host_log(*, stream: TextIO, **kwargs: Any) -> None:
    """Emit one structured JSON log line to the given stream (stderr in prod)."""
    _logger.emit(stream=stream, **kwargs)


def map_transport_failure(
    *,
    message: str,
    trace_id: str,
    timestamp_utc: str,
) -> dict[str, Any]:
    """Map transport failure to TRANSPORT_ERROR Envelope; never echo raw message."""
    _ = message  # intentionally discarded — clients get generic text only
    envelope: OperationEnvelope[None] = OperationEnvelope.fail(
        ErrorInfo(
            code=ErrorCode.TRANSPORT_ERROR.value,
            message="Transport failed",
            context={"transport": "stdio"},
        ),
        EnvelopeMeta(
            trace_id=trace_id,
            timestamp_utc=timestamp_utc,
            operation="stdio_transport",
            duration_ms=0,
        ),
    )
    return envelope_to_jsonable(envelope)


def main() -> None:
    settings = load_stdio_settings(os.environ)
    container = resolve_app_container(settings, os.environ)
    server = build_stdio_server(container=container)
    emit_host_log(
        stream=sys.stderr,
        timestamp_utc="1970-01-01T00:00:00Z",
        level="INFO",
        event="stdio.host.start",
        trace_id="stdio-host",
        operation="stdio_host",
        status="ok",
        duration_ms=0,
        transport="stdio",
    )
    server.run(transport="stdio", show_banner=False)


if __name__ == "__main__":
    main()

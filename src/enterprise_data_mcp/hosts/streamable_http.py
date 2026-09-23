"""Streamable HTTP transport host — /mcp + health; loopback only (Step 11)."""

from __future__ import annotations

import os
from typing import Any

import uvicorn

from enterprise_data_mcp.adapters.inbound.mcp.envelope_codec import (
    envelope_to_jsonable,
)
from enterprise_data_mcp.bootstrap.container import resolve_app_container
from enterprise_data_mcp.bootstrap.settings import load_http_settings
from enterprise_data_mcp.domain.errors import ErrorCode
from enterprise_data_mcp.domain.models import EnvelopeMeta, ErrorInfo, OperationEnvelope
from enterprise_data_mcp.hosts import build_streamable_http_app


def map_transport_failure(
    *,
    message: str,
    trace_id: str,
    timestamp_utc: str,
) -> dict[str, Any]:
    """Map transport failure to TRANSPORT_ERROR; never echo raw message."""
    _ = message
    envelope: OperationEnvelope[None] = OperationEnvelope.fail(
        ErrorInfo(
            code=ErrorCode.TRANSPORT_ERROR.value,
            message="Transport failed",
            context={"transport": "streamable_http"},
        ),
        EnvelopeMeta(
            trace_id=trace_id,
            timestamp_utc=timestamp_utc,
            operation="streamable_http_transport",
            duration_ms=0,
        ),
    )
    return envelope_to_jsonable(envelope)


def main() -> None:
    settings = load_http_settings(os.environ)
    container = resolve_app_container(settings, os.environ)
    app = build_streamable_http_app(container=container, settings=settings)
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_level="warning",
    )


if __name__ == "__main__":
    main()

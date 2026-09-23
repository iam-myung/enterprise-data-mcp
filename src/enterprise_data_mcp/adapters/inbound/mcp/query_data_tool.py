"""MCP Tool adapter for query_data (API §6.1 / Step 9.3).

Maps ExecuteReadQuery → dual-channel Envelope. No Host / Agent / extra Tools.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from fastmcp import FastMCP

from enterprise_data_mcp.adapters.inbound.mcp.envelope_codec import (
    envelope_to_jsonable,
)
from enterprise_data_mcp.application.query_service import ExecuteReadQuery
from enterprise_data_mcp.domain.models import CallerContext

QUERY_DATA_TOOL_NAME = "query_data"


def invoke_query_data(
    *,
    use_case: ExecuteReadQuery,
    caller: CallerContext,
    call_id: str,
    request: Mapping[str, object],
) -> dict[str, Any]:
    envelope = use_case.execute(
        caller=caller, call_id=call_id, request=request
    )
    return envelope_to_jsonable(envelope)


def build_query_data_mcp(
    *,
    use_case: ExecuteReadQuery,
    caller: CallerContext,
    call_id: str,
) -> FastMCP:
    mcp = FastMCP("enterprise-data-query")

    @mcp.tool(
        name=QUERY_DATA_TOOL_NAME,
        description="Structured read-only query against an authorized dataset",
    )
    def query_data(request: dict[str, Any]) -> dict[str, Any]:
        return invoke_query_data(
            use_case=use_case,
            caller=caller,
            call_id=uuid.uuid4().hex,
            request=request,
        )

    return mcp

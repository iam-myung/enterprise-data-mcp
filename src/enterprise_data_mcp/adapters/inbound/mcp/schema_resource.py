"""MCP Resource template adapter for dataset schema (API §5.2 / Step 9.2).

Maps GetAuthorizedSchema → Envelope JSON. No Host process. No new URIs.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastmcp import FastMCP

from enterprise_data_mcp.adapters.inbound.mcp.envelope_codec import (
    envelope_to_jsonable,
)
from enterprise_data_mcp.adapters.inbound.mcp.uri_constants import (
    SCHEMA_URI_TEMPLATE,
)
from enterprise_data_mcp.application.catalog_service import GetAuthorizedSchema
from enterprise_data_mcp.domain.models import CallerContext


def read_schema_resource(
    *,
    use_case: GetAuthorizedSchema,
    caller: CallerContext,
    call_id: str,
    dataset_id: str,
) -> dict[str, Any]:
    envelope = use_case.execute(
        caller=caller, call_id=call_id, dataset_id=dataset_id
    )
    return envelope_to_jsonable(envelope)


def build_schema_mcp(
    *,
    use_case: GetAuthorizedSchema,
    caller: CallerContext,
    call_id: str,
) -> FastMCP:
    mcp = FastMCP("enterprise-data-schema")

    @mcp.resource(
        SCHEMA_URI_TEMPLATE,
        name="schema",
        description="Authorized dataset schema",
        mime_type="application/json",
    )
    def _schema(dataset_id: str) -> str:
        payload = read_schema_resource(
            use_case=use_case,
            caller=caller,
            call_id=uuid.uuid4().hex,
            dataset_id=dataset_id,
        )
        return json.dumps(payload, ensure_ascii=False)

    return mcp

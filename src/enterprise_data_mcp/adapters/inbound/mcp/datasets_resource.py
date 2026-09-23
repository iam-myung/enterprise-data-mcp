"""MCP Resource adapter for enterprise-data://datasets (API §5.1 / Step 9.1).

Maps ListAuthorizedDatasets → Envelope JSON. No Host process.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastmcp import FastMCP

from enterprise_data_mcp.adapters.inbound.mcp.envelope_codec import (
    envelope_to_jsonable,
)
from enterprise_data_mcp.adapters.inbound.mcp.uri_constants import DATASETS_URI
from enterprise_data_mcp.application.catalog_service import ListAuthorizedDatasets
from enterprise_data_mcp.domain.models import CallerContext


def read_datasets_resource(
    *,
    use_case: ListAuthorizedDatasets,
    caller: CallerContext,
    call_id: str,
) -> dict[str, Any]:
    envelope = use_case.execute(caller=caller, call_id=call_id)
    return envelope_to_jsonable(envelope)


def build_datasets_mcp(
    *,
    use_case: ListAuthorizedDatasets,
    caller: CallerContext,
    call_id: str,
) -> FastMCP:
    mcp = FastMCP("enterprise-data-datasets")

    @mcp.resource(
        DATASETS_URI,
        name="datasets",
        description="Authorized dataset list",
        mime_type="application/json",
    )
    def _datasets() -> str:
        payload = read_datasets_resource(
            use_case=use_case, caller=caller, call_id=uuid.uuid4().hex
        )
        return json.dumps(payload, ensure_ascii=False)

    return mcp

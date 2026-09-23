"""Compose inbound MCP Resources + Tools into one FastMCP surface (Step 10)."""

from __future__ import annotations

from fastmcp import FastMCP

from enterprise_data_mcp.adapters.inbound.mcp.datasets_resource import (
    build_datasets_mcp,
)
from enterprise_data_mcp.adapters.inbound.mcp.query_data_tool import (
    build_query_data_mcp,
)
from enterprise_data_mcp.adapters.inbound.mcp.schema_resource import (
    build_schema_mcp,
)
from enterprise_data_mcp.application.catalog_service import (
    GetAuthorizedSchema,
    ListAuthorizedDatasets,
)
from enterprise_data_mcp.application.query_service import ExecuteReadQuery
from enterprise_data_mcp.domain.models import CallerContext

SERVER_NAME = "enterprise-data-mcp"


def compose_enterprise_mcp(
    *,
    list_datasets: ListAuthorizedDatasets,
    get_schema: GetAuthorizedSchema,
    execute_query: ExecuteReadQuery,
    caller: CallerContext,
    call_id: str,
) -> FastMCP:
    """Mount datasets, schema, and query_data without namespaces (API URIs/names intact)."""
    mcp = FastMCP(SERVER_NAME)
    mcp.mount(
        build_datasets_mcp(
            use_case=list_datasets, caller=caller, call_id=call_id
        ),
        namespace=None,
    )
    mcp.mount(
        build_schema_mcp(
            use_case=get_schema, caller=caller, call_id=call_id
        ),
        namespace=None,
    )
    mcp.mount(
        build_query_data_mcp(
            use_case=execute_query, caller=caller, call_id=call_id
        ),
        namespace=None,
    )
    return mcp

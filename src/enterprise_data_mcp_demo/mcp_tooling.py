"""MCP tooling surface for demo agent (query_data only; no server imports)."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol

import anyio
from fastmcp import Client
from fastmcp.client.transports import StdioTransport, StreamableHttpTransport

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_TOOL_NAME = "query_data"


class McpQueryPort(Protocol):
    def call_query_data(self, args: Mapping[str, object]) -> Mapping[str, object]:
        """Invoke MCP tool query_data; returns OperationEnvelope-shaped mapping."""


class NullMcpClient:
    """Misconfig sentinel — not a CLI success path."""

    def call_query_data(self, args: Mapping[str, object]) -> Mapping[str, object]:
        raise RuntimeError("MCP client not configured")


def _envelope_from_call(call: Any) -> dict[str, Any]:
    if getattr(call, "structured_content", None) is not None:
        payload = call.structured_content
    else:
        data = getattr(call, "data", None)
        if isinstance(data, dict):
            payload = data
        else:
            content = getattr(call, "content", None) or []
            payload = json.loads(content[0].text)
    if not isinstance(payload, dict):
        raise TypeError(f"expected envelope mapping, got {type(payload)!r}")
    return payload


class StdioMcpClient:
    """Public stdio Host client (one subprocess per query_data)."""

    def __init__(self, *, environ: Mapping[str, str] | None = None) -> None:
        self._environ = dict(environ) if environ is not None else dict(os.environ)

    def call_query_data(self, args: Mapping[str, object]) -> Mapping[str, object]:
        env = {
            **self._environ,
            "MCP_TRANSPORT": "stdio",
            "PYTHONUNBUFFERED": "1",
        }

        async def _run() -> dict[str, Any]:
            # Windows+pytest: sys.stderr may lack fileno(); use a real log file.
            import tempfile

            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                suffix="-mcp-stdio.log",
                delete=False,
            ) as log_fp:
                log_path = Path(log_fp.name)
            try:
                transport = StdioTransport(
                    command=sys.executable,
                    args=["-m", "enterprise_data_mcp.hosts.stdio"],
                    cwd=str(_PROJECT_ROOT),
                    env=env,
                    log_file=log_path,
                )
                async with Client(transport) as client:
                    _ = client.protocol_version
                    call = await client.call_tool(
                        _TOOL_NAME,
                        {"request": dict(args)},
                    )
                    return _envelope_from_call(call)
            finally:
                try:
                    log_path.unlink(missing_ok=True)
                except OSError:
                    pass

        return anyio.run(_run)


class StreamableHttpMcpClient:
    """Public Streamable HTTP Host client (Compose / local Uvicorn)."""

    def __init__(
        self,
        *,
        url: str,
        origin: str = "http://127.0.0.1:3000",
    ) -> None:
        self._url = url
        self._origin = origin

    def call_query_data(self, args: Mapping[str, object]) -> Mapping[str, object]:
        async def _run() -> dict[str, Any]:
            transport = StreamableHttpTransport(
                url=self._url,
                headers={"Origin": self._origin},
            )
            async with Client(transport) as client:
                call = await client.call_tool(
                    _TOOL_NAME,
                    {"request": dict(args)},
                )
                return _envelope_from_call(call)

        return anyio.run(_run)

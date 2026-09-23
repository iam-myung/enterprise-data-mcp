"""Demo agent CLI entry — public MCP Host + model wiring (BUG-03)."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from enterprise_data_mcp_demo.agent import DemoAgent
from enterprise_data_mcp_demo.clock import FixedClock
from enterprise_data_mcp_demo.mcp_tooling import (
    StdioMcpClient,
    StreamableHttpMcpClient,
)
from enterprise_data_mcp_demo.model_port import DeterministicQueryModel, OpenAICompatModel


@dataclass(frozen=True, slots=True)
class DemoRuntime:
    model: Any
    mcp: Any
    clock: Any


def _require_model_env(env: Mapping[str, str], name: str) -> str:
    value = str(env.get(name, "")).strip()
    if not value:
        raise ValueError(
            f"{name} is required when DEMO_MODEL is openai|real (SPEC §12)"
        )
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="enterprise-data-mcp-demo",
        description="LangGraph demo agent client (consumes public MCP only).",
    )
    parser.add_argument("message", nargs="?", default="", help="Natural language query")
    return parser


def build_runtime(environ: Mapping[str, str] | None = None) -> DemoRuntime:
    """Assemble model + public MCP client from env (SPEC §14.2 / BUG-03)."""
    env = {**os.environ, **(dict(environ) if environ is not None else {})}

    model_kind = str(env.get("DEMO_MODEL", "deterministic")).strip().lower()
    if model_kind in {"deterministic", "demo", "fake"}:
        model: Any = DeterministicQueryModel()
    elif model_kind in {"openai", "real"}:
        model = OpenAICompatModel(
            api_key=_require_model_env(env, "MODEL_API_KEY"),
            base_url=_require_model_env(env, "MODEL_BASE_URL"),
            model_name=_require_model_env(env, "MODEL_NAME"),
        )
    else:
        raise ValueError(
            f"DEMO_MODEL must be deterministic|openai|real, got {model_kind!r}"
        )

    transport = str(env.get("DEMO_MCP_TRANSPORT", "stdio")).strip().lower()
    if transport in {"http", "streamable_http", "streamable-http"}:
        url = str(env.get("DEMO_MCP_URL", "http://127.0.0.1:18080/mcp")).strip()
        origin = str(env.get("DEMO_MCP_ORIGIN", "http://127.0.0.1:3000")).strip()
        mcp: Any = StreamableHttpMcpClient(url=url, origin=origin)
    elif transport == "stdio":
        mcp = StdioMcpClient(environ=env)
    else:
        raise ValueError(
            f"DEMO_MCP_TRANSPORT must be stdio|streamable_http, got {transport!r}"
        )

    clock_raw = str(env.get("DEMO_CLOCK_UTC", "")).strip()
    if clock_raw:
        clock: Any = FixedClock(now_utc=clock_raw)
    else:
        clock = FixedClock(
            now_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        )
    return DemoRuntime(model=model, mcp=mcp, clock=clock)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.message:
        print("usage: provide a natural-language message", file=sys.stderr)
        return 2
    runtime = build_runtime()
    agent = DemoAgent(model=runtime.model, mcp=runtime.mcp, clock=runtime.clock)
    answer = agent.handle(args.message)
    print(answer.text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

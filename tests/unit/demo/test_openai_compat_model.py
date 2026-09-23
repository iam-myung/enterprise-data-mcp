"""Unit tests for OpenAICompatModel — mocked HTTP, no real network."""

from __future__ import annotations

import io
import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


def _chat_response_body(content: str, *, status: int = 200) -> bytes:
    payload = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": content,
                }
            }
        ]
    }
    return json.dumps(payload).encode("utf-8")


def _mock_urlopen(body: bytes, *, status: int = 200):
    resp = MagicMock()
    resp.read.return_value = body
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    resp.status = status
    resp.getcode.return_value = status
    return resp


def test_openai_compat_parses_tool_json() -> None:
    from enterprise_data_mcp_demo.model_port import OpenAICompatModel

    tool_json = json.dumps(
        {
            "kind": "tool",
            "name": "query_data",
            "arguments": {
                "dataset_id": "sales_inventory_daily",
                "projection": ["product_name"],
                "filters": [],
                "aggregations": [],
                "group_by": [],
                "order_by": [],
                "limit": 10,
            },
        },
        ensure_ascii=False,
    )
    body = _chat_response_body(f"```json\n{tool_json}\n```")

    model = OpenAICompatModel(
        api_key="test-key",
        base_url="https://example.invalid/v1",
        model_name="test-model",
    )
    with patch(
        "enterprise_data_mcp_demo.model_port.urlopen",
        return_value=_mock_urlopen(body),
    ) as mocked:
        result = model.complete(
            user_message="列出产品",
            catalog_text="Authorized dataset: sales_inventory_daily",
        )

    assert mocked.called
    assert result["kind"] == "tool"
    assert result["name"] == "query_data"
    args = result["arguments"]
    assert isinstance(args, dict)
    assert args["dataset_id"] == "sales_inventory_daily"
    assert args["projection"] == ["product_name"]


def test_openai_compat_parses_final_json() -> None:
    from enterprise_data_mcp_demo.model_port import OpenAICompatModel

    final_json = json.dumps(
        {"kind": "final", "text": "需要先查询才能回答。"},
        ensure_ascii=False,
    )
    body = _chat_response_body(final_json)

    model = OpenAICompatModel(
        api_key="test-key",
        base_url="https://example.invalid/v1",
        model_name="test-model",
    )
    with patch(
        "enterprise_data_mcp_demo.model_port.urlopen",
        return_value=_mock_urlopen(body),
    ):
        result = model.complete(
            user_message="你好",
            catalog_text="Authorized dataset: sales_inventory_daily",
        )

    assert result["kind"] == "final"
    assert "查询" in str(result["text"]) or "回答" in str(result["text"])


def test_openai_compat_http_error_refuses_numbers() -> None:
    from enterprise_data_mcp_demo.model_port import OpenAICompatModel
    from urllib.error import HTTPError

    model = OpenAICompatModel(
        api_key="test-key",
        base_url="https://example.invalid/v1",
        model_name="test-model",
    )
    http_err = HTTPError(
        url="https://example.invalid/v1/chat/completions",
        code=503,
        msg="Service Unavailable",
        hdrs=None,  # type: ignore[arg-type]
        fp=io.BytesIO(b"unavailable"),
    )
    with patch(
        "enterprise_data_mcp_demo.model_port.urlopen",
        side_effect=http_err,
    ):
        result = model.complete(
            user_message="销售额是多少？",
            catalog_text="Authorized dataset: sales_inventory_daily",
        )

    assert result["kind"] == "final"
    text = str(result["text"])
    # Must refuse / ask retry — never invent business figures.
    assert any(tok in text for tok in ("重试", "不可用", "失败", "无法"))
    for digit_run in ("123", "456", "789", "1000", "99.9"):
        assert digit_run not in text


def test_cli_openai_requires_model_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from enterprise_data_mcp_demo import cli

    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("MODEL_BASE_URL", raising=False)
    monkeypatch.delenv("MODEL_NAME", raising=False)

    with pytest.raises(ValueError, match="MODEL_"):
        cli.build_runtime(
            {
                "DEMO_MODEL": "openai",
                "DEMO_MCP_TRANSPORT": "stdio",
                "MCP_CONTAINER": "mysql",
                "MCP_CALLER_ID": "unit",
                "MCP_POLICY_PROFILE": "demo_readonly",
                "MCP_TRANSPORT": "stdio",
            }
        )


def test_cli_openai_wires_compat_model() -> None:
    from enterprise_data_mcp_demo import cli
    from enterprise_data_mcp_demo.model_port import (
        DeterministicQueryModel,
        OpenAICompatModel,
    )

    runtime = cli.build_runtime(
        {
            "DEMO_MODEL": "real",
            "MODEL_API_KEY": "test-key",
            "MODEL_BASE_URL": "https://example.invalid/v1",
            "MODEL_NAME": "test-model",
            "DEMO_MCP_TRANSPORT": "stdio",
            "MCP_CONTAINER": "mysql",
            "MCP_CALLER_ID": "unit",
            "MCP_POLICY_PROFILE": "demo_readonly",
            "MCP_TRANSPORT": "stdio",
        }
    )
    model: Any = runtime.model
    assert isinstance(model, OpenAICompatModel)
    assert not isinstance(model, DeterministicQueryModel)

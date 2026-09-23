"""Model port for demo agent (injectable; unit tests use fakes)."""

from __future__ import annotations

import json
import re
from typing import Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_REFUSE_TEXT = "模型服务暂时不可用或响应无效，请稍后重试。无法给出确定性企业数据答案。"
_SYSTEM_PROMPT = (
    "You are a demo agent for read-only enterprise data queries. "
    "Reply with ONLY a single JSON object (no markdown, no prose). "
    'Either {"kind":"tool","name":"query_data","arguments":{...}} '
    'or {"kind":"final","text":"..."}. '
    "query_data arguments MUST use these exact field names only: "
    "dataset_id (string), projection (string array), filters (array), "
    "aggregations (array), group_by (array), order_by (array), limit (int). "
    'Example: {"kind":"tool","name":"query_data","arguments":'
    '{"dataset_id":"sales_inventory_daily","projection":["product_name"],'
    '"filters":[],"aggregations":[],"group_by":[],"order_by":[],"limit":10}}. '
    "Never use aliases like dataset, columns, fields, table, or sql. "
    "Do not invent business numbers without a successful query_data tool result."
)
_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.IGNORECASE)


class ModelPort(Protocol):
    def complete(
        self, *, user_message: str, catalog_text: str
    ) -> Mapping[str, object]:
        """Return {"kind": "final"|"tool", ...}."""


class EchoModel:
    """Test-only stub: never selects tools (not a CLI success path)."""

    def complete(self, *, user_message: str, catalog_text: str) -> Mapping[str, object]:
        return {
            "kind": "final",
            "text": "未调用查询工具，无法给出确定性企业数据答案。",
        }


class DeterministicQueryModel:
    """Offline/demo tool selector: first turn calls query_data, then narrates."""

    def __init__(self) -> None:
        self._n = 0

    def complete(self, *, user_message: str, catalog_text: str) -> Mapping[str, object]:
        _ = user_message, catalog_text
        self._n += 1
        if self._n == 1:
            return {
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
            }
        return {"kind": "final", "text": "查询完成（确定性模型）。"}


class OpenAICompatModel:
    """OpenAI-compatible chat completions adapter (stdlib urllib; no openai SDK)."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model_name: str,
        timeout_s: float = 60.0,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model_name = model_name
        self._timeout_s = timeout_s

    def complete(self, *, user_message: str, catalog_text: str) -> Mapping[str, object]:
        url = f"{self._base_url}/chat/completions"
        payload = {
            "model": self._model_name,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Catalog:\n{catalog_text}\n\nUser message:\n{user_message}"
                    ),
                },
            ],
        }
        body = json.dumps(payload).encode("utf-8")
        request = Request(
            url,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=self._timeout_s) as resp:
                raw = resp.read()
        except (HTTPError, URLError, TimeoutError, OSError):
            return {"kind": "final", "text": _REFUSE_TEXT}

        try:
            envelope = json.loads(raw.decode("utf-8"))
            content = (
                envelope["choices"][0]["message"]["content"]
                if isinstance(envelope, dict)
                else None
            )
            if not isinstance(content, str):
                return {"kind": "final", "text": _REFUSE_TEXT}
            return self._parse_decision(content)
        except (json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError):
            return {"kind": "final", "text": _REFUSE_TEXT}

    def _parse_decision(self, content: str) -> Mapping[str, object]:
        text = content.strip()
        fence = _FENCE_RE.search(text)
        if fence:
            text = fence.group(1).strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return {"kind": "final", "text": _REFUSE_TEXT}
        if not isinstance(data, dict):
            return {"kind": "final", "text": _REFUSE_TEXT}

        kind = str(data.get("kind", "")).strip().lower()
        if kind == "tool":
            name = str(data.get("name", "")).strip()
            arguments = data.get("arguments")
            if name != "query_data" or not isinstance(arguments, dict):
                return {"kind": "final", "text": _REFUSE_TEXT}
            return {"kind": "tool", "name": name, "arguments": arguments}
        if kind == "final":
            final_text = data.get("text")
            if not isinstance(final_text, str) or not final_text.strip():
                return {"kind": "final", "text": _REFUSE_TEXT}
            return {"kind": "final", "text": final_text.strip()}
        return {"kind": "final", "text": _REFUSE_TEXT}

"""LangGraph-ready Demo Agent — NL turn with hallucination gate (SPEC §14.2)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from enterprise_data_mcp_demo.query_schema import ToolArgError, validate_query_request_args

_CATALOG_HINT = (
    "Authorized dataset_id: sales_inventory_daily. "
    "Call query_data with fields dataset_id, projection, filters, "
    "aggregations, group_by, order_by, limit. "
    'Example projection for product names: ["product_name"].'
)


@dataclass(frozen=True, slots=True)
class DemoAnswer:
    text: str
    dataset_id: str | None
    queried_at_utc: str | None
    row_count: int | None
    tool_called: bool
    tool_succeeded: bool


class DemoAgent:
    """Minimal agent loop: model → optional validated query_data → provenance answer."""

    def __init__(self, *, model: Any, mcp: Any, clock: Any) -> None:
        self._model = model
        self._mcp = mcp
        self._clock = clock

    def handle(self, user_message: str) -> DemoAnswer:
        first = self._model.complete(
            user_message=user_message,
            catalog_text=_CATALOG_HINT,
        )
        kind = str(first.get("kind", ""))

        if kind == "tool":
            return self._handle_tool(user_message=user_message, decision=first)

        # Final without a successful query_data → refuse fabricated enterprise facts.
        return DemoAnswer(
            text="未调用查询工具，无法给出确定性企业数据答案。请先通过 query_data 查询。",
            dataset_id=None,
            queried_at_utc=None,
            row_count=None,
            tool_called=False,
            tool_succeeded=False,
        )

    def _handle_tool(
        self, *, user_message: str, decision: Mapping[str, object]
    ) -> DemoAnswer:
        name = str(decision.get("name", ""))
        if name != "query_data":
            return DemoAnswer(
                text="不支持的工具调用，无法完成查询。",
                dataset_id=None,
                queried_at_utc=None,
                row_count=None,
                tool_called=False,
                tool_succeeded=False,
            )

        raw_args = decision.get("arguments")
        if not isinstance(raw_args, Mapping):
            return DemoAnswer(
                text="工具参数无效：arguments 必须为对象。",
                dataset_id=None,
                queried_at_utc=None,
                row_count=None,
                tool_called=True,
                tool_succeeded=False,
            )

        try:
            args = validate_query_request_args(raw_args)
        except ToolArgError as exc:
            return DemoAnswer(
                text=f"工具参数校验失败：{exc}",
                dataset_id=None,
                queried_at_utc=None,
                row_count=None,
                tool_called=True,
                tool_succeeded=False,
            )

        envelope = self._mcp.call_query_data(args)
        success = bool(envelope.get("success"))
        if not success:
            err = envelope.get("error") if isinstance(envelope.get("error"), Mapping) else {}
            code = err.get("code", "ERROR") if isinstance(err, Mapping) else "ERROR"
            return DemoAnswer(
                text=f"查询失败（{code}）：数据源不可用或调用错误，无法给出确定性数据答案。",
                dataset_id=str(args["dataset_id"]),
                queried_at_utc=None,
                row_count=None,
                tool_called=True,
                tool_succeeded=False,
            )

        data = envelope.get("data") if isinstance(envelope.get("data"), Mapping) else {}
        meta = envelope.get("meta") if isinstance(envelope.get("meta"), Mapping) else {}
        dataset_id = str(args["dataset_id"])
        row_count = data.get("row_count") if isinstance(data, Mapping) else None
        if row_count is not None:
            try:
                row_count = int(row_count)
            except (TypeError, ValueError):
                row_count = None
        queried_at = None
        if isinstance(meta, Mapping):
            ts = meta.get("timestamp_utc")
            if isinstance(ts, str) and ts:
                queried_at = ts
        if not queried_at:
            queried_at = self._clock.now()

        # Optional second model turn for narrative (deterministic fakes in tests).
        narrative = ""
        follow = self._model.complete(
            user_message=user_message,
            catalog_text=f"tool_result rows={row_count} dataset={dataset_id}",
        )
        if str(follow.get("kind", "")) == "final":
            narrative = str(follow.get("text", "")).strip()

        provenance = (
            f"数据集：{dataset_id}；查询时间：{queried_at}；返回条数：{row_count}"
        )
        body = f"{narrative}\n{provenance}".strip() if narrative else provenance
        return DemoAnswer(
            text=body,
            dataset_id=dataset_id,
            queried_at_utc=queried_at,
            row_count=row_count,
            tool_called=True,
            tool_succeeded=True,
        )

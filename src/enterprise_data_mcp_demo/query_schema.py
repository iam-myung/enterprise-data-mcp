"""Local QueryRequest tool-arg validation mirroring API §6.1 (no server imports)."""

from __future__ import annotations

from typing import Mapping

_ALLOWED_KEYS = frozenset(
    {
        "dataset_id",
        "projection",
        "filters",
        "aggregations",
        "group_by",
        "order_by",
        "limit",
    }
)
_WRITE_KEYS = frozenset({"raw_sql", "sql", "statement"})
_MIN_LIMIT = 1
_MAX_LIMIT = 100
_DEFAULT_LIMIT = 50


class ToolArgError(Exception):
    """Demo-local tool argument validation failure."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        field: str | None = None,
        reason: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.field = field
        self.context: dict[str, object] = {}
        if field is not None:
            self.context["field"] = field
        if reason is not None:
            self.context["reason"] = reason


def validate_query_request_args(payload: Mapping[str, object]) -> dict[str, object]:
    """Validate and normalize tool arguments for query_data."""
    if not isinstance(payload, Mapping):
        raise ToolArgError(
            "VALIDATION_ERROR",
            "payload must be an object",
            field="payload",
            reason="not_object",
        )

    keys = set(payload.keys())
    write_hit = keys & _WRITE_KEYS
    if write_hit:
        raise ToolArgError(
            "WRITE_OPERATION_FORBIDDEN",
            "write-oriented fields are forbidden",
            field=sorted(write_hit)[0],
            reason="write_field",
        )

    unknown = keys - _ALLOWED_KEYS
    if unknown:
        raise ToolArgError(
            "VALIDATION_ERROR",
            f"unknown fields: {sorted(unknown)}",
            field=sorted(unknown)[0],
            reason="unknown_field",
        )

    dataset_id = payload.get("dataset_id")
    if not isinstance(dataset_id, str) or not dataset_id.strip():
        raise ToolArgError(
            "VALIDATION_ERROR",
            "dataset_id is required",
            field="dataset_id",
            reason="required",
        )

    projection = payload.get("projection", [])
    aggregations = payload.get("aggregations", [])
    if projection is None:
        projection = []
    if aggregations is None:
        aggregations = []
    if not isinstance(projection, (list, tuple)):
        raise ToolArgError(
            "VALIDATION_ERROR",
            "projection must be a list",
            field="projection",
            reason="type",
        )
    if not isinstance(aggregations, (list, tuple)):
        raise ToolArgError(
            "VALIDATION_ERROR",
            "aggregations must be a list",
            field="aggregations",
            reason="type",
        )

    has_proj = len(projection) > 0
    has_agg = len(aggregations) > 0
    if has_proj and has_agg:
        raise ToolArgError(
            "VALIDATION_ERROR",
            "detail and aggregate modes are mutually exclusive",
            field="projection",
            reason="mode_mix",
        )
    if not has_proj and not has_agg:
        raise ToolArgError(
            "VALIDATION_ERROR",
            "either projection or aggregations is required",
            field="projection",
            reason="empty_modes",
        )

    if "limit" in payload:
        limit_raw = payload["limit"]
        if not isinstance(limit_raw, int) or isinstance(limit_raw, bool):
            raise ToolArgError(
                "VALIDATION_ERROR",
                "limit must be an integer",
                field="limit",
                reason="type",
            )
        if limit_raw < _MIN_LIMIT or limit_raw > _MAX_LIMIT:
            raise ToolArgError(
                "VALIDATION_ERROR",
                f"limit must be between {_MIN_LIMIT} and {_MAX_LIMIT}",
                field="limit",
                reason="range",
            )
        limit = limit_raw
    else:
        limit = _DEFAULT_LIMIT

    filters = payload.get("filters", [])
    group_by = payload.get("group_by", [])
    order_by = payload.get("order_by", [])
    if filters is None:
        filters = []
    if group_by is None:
        group_by = []
    if order_by is None:
        order_by = []

    return {
        "dataset_id": dataset_id,
        "projection": list(projection),
        "filters": list(filters),
        "aggregations": list(aggregations),
        "group_by": list(group_by),
        "order_by": list(order_by),
        "limit": limit,
    }

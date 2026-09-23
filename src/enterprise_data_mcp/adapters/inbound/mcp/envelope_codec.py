"""Serialize OperationEnvelope to JSON-compatible dicts (API §3 / Steps 9.1–9.3)."""

from __future__ import annotations

from enum import Enum
from typing import Any

from enterprise_data_mcp.application.catalog_service import DatasetList, DatasetSchema
from enterprise_data_mcp.domain.models import (
    DatasetSummary,
    ErrorInfo,
    FieldSummary,
    OperationEnvelope,
    QueryResult,
)


def envelope_to_jsonable(envelope: OperationEnvelope[Any]) -> dict[str, Any]:
    return {
        "success": envelope.success,
        "data": _data_to_jsonable(envelope.data),
        "error": _error_to_jsonable(envelope.error),
        "meta": {
            "trace_id": envelope.meta.trace_id,
            "timestamp_utc": envelope.meta.timestamp_utc,
            "operation": envelope.meta.operation,
            "duration_ms": envelope.meta.duration_ms,
        },
    }


def _data_to_jsonable(data: object | None) -> object | None:
    if data is None:
        return None
    if isinstance(data, DatasetList):
        return {
            "datasets": [_summary_to_jsonable(item) for item in data.datasets],
            "count": data.count,
        }
    if isinstance(data, DatasetSchema):
        return {
            "dataset": _summary_to_jsonable(data.dataset),
            "fields": [_field_to_jsonable(item) for item in data.fields],
            "default_limit": data.default_limit,
            "max_limit": data.max_limit,
            "allowed_filter_operators": list(data.allowed_filter_operators),
        }
    if isinstance(data, QueryResult):
        return _query_result_to_jsonable(data)
    return data


def _query_result_to_jsonable(result: QueryResult) -> dict[str, Any]:
    columns = list(result.columns)
    rows: list[dict[str, object]] = []
    for row in result.rows:
        rows.append({columns[i]: row[i] for i in range(len(columns))})
    return {
        "result_status": _enum_value(result.result_status),
        "columns": columns,
        "rows": rows,
        "row_count": result.row_count,
        "truncated": result.truncated,
        "source": {
            "dataset_id": result.source.dataset_id,
            "queried_at_utc": result.source.queried_at_utc,
        },
    }

def _summary_to_jsonable(summary: DatasetSummary) -> dict[str, Any]:
    return {
        "dataset_id": summary.dataset_id,
        "title": summary.title,
        "description": summary.description,
        "capabilities": [_enum_value(cap) for cap in summary.capabilities],
    }


def _field_to_jsonable(field: FieldSummary) -> dict[str, Any]:
    return {
        "field_id": field.field_id,
        "title": field.title,
        "value_type": _enum_value(field.value_type),
        "nullable": field.nullable,
        "filterable": field.filterable,
        "aggregatable": field.aggregatable,
        "sortable": field.sortable,
    }


def _error_to_jsonable(error: ErrorInfo | None) -> dict[str, Any] | None:
    if error is None:
        return None
    return {
        "code": error.code,
        "message": error.message,
        "context": dict(error.context),
    }


def _enum_value(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    return value

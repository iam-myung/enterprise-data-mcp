"""QueryRequest deterministic rules (SPEC §7.3 / Step 5.1).

Pure Domain functions. Standard library + domain only.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import NoReturn, cast

from enterprise_data_mcp.domain.errors import (
    AggregateFunction,
    ErrorCode,
    FilterOperator,
    SortDirection,
)
from enterprise_data_mcp.domain.models import (
    AggregationSpec,
    FilterSpec,
    OrderSpec,
    QueryRequest,
    ValueType,
)

_ALLOWED_TOP_LEVEL: frozenset[str] = frozenset(
    {
        "dataset_id",
        "projection",
        "filters",
        "aggregations",
        "group_by",
        "order_by",
        "limit",
        "operation",
    }
)
_WRITE_KEYS: frozenset[str] = frozenset({"raw_sql", "sql", "statement"})
_WRITE_OPERATIONS: frozenset[str] = frozenset(
    {"INSERT", "UPDATE", "DELETE", "DDL", "DROP", "TRUNCATE"}
)
_COMPARISON_OPS: frozenset[FilterOperator] = frozenset(
    {
        FilterOperator.EQ,
        FilterOperator.NE,
        FilterOperator.GT,
        FilterOperator.GTE,
        FilterOperator.LT,
        FilterOperator.LTE,
    }
)
_NULL_OPS: frozenset[FilterOperator] = frozenset(
    {FilterOperator.IS_NULL, FilterOperator.IS_NOT_NULL}
)
_NUMERIC_TYPES: frozenset[ValueType] = frozenset(
    {ValueType.INTEGER, ValueType.NUMBER}
)
_COMPARABLE_TYPES: frozenset[ValueType] = frozenset(
    {
        ValueType.STRING,
        ValueType.INTEGER,
        ValueType.NUMBER,
        ValueType.BOOLEAN,
        ValueType.DATE,
        ValueType.DATETIME,
    }
)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MAX_STRING_LEN = 256
_MAX_PROJECTION = 20
_MAX_FILTERS = 20
_MAX_AGGREGATIONS = 10
_MAX_GROUP_BY = 5
_MAX_ORDER_BY = 5
_MAX_IN_VALUES = 100


class DomainRuleError(Exception):
    """Domain validation failure mapped to an ErrorCode."""

    def __init__(
        self,
        message: str,
        *,
        code: ErrorCode,
        context: Mapping[str, object],
    ) -> None:
        super().__init__(message)
        self.code = code.value
        self.message = message
        self.context = dict(context)


@dataclass(frozen=True, slots=True)
class FieldRuleMeta:
    value_type: ValueType
    filterable: bool = True
    aggregatable: bool = True
    sortable: bool = True


def validate_query_request(
    payload: Mapping[str, object],
    *,
    allowed_fields: Mapping[str, FieldRuleMeta],
    default_limit: int = 50,
    max_limit: int = 100,
) -> QueryRequest:
    if not isinstance(payload, Mapping):
        _validation("payload", "invalid_type")

    for key in _WRITE_KEYS:
        if key in payload:
            raise DomainRuleError(
                "write intent is forbidden",
                code=ErrorCode.WRITE_OPERATION_FORBIDDEN,
                context={"operation": key},
            )

    if "operation" in payload:
        raw_op = payload["operation"]
        op_text = str(raw_op).upper() if raw_op is not None else ""
        if op_text in _WRITE_OPERATIONS:
            raise DomainRuleError(
                "write operation is forbidden",
                code=ErrorCode.WRITE_OPERATION_FORBIDDEN,
                context={"operation": op_text},
            )

    for key in payload:
        if key not in _ALLOWED_TOP_LEVEL:
            _validation(str(key), "unknown_field")

    dataset_id = payload.get("dataset_id")
    if not isinstance(dataset_id, str) or not dataset_id:
        _validation("dataset_id", "required")

    projection = _as_str_list(payload.get("projection", []), "projection")
    filters_raw = payload.get("filters", [])
    aggregations_raw = payload.get("aggregations", [])
    group_by = _as_str_list(payload.get("group_by", []), "group_by")
    order_by_raw = payload.get("order_by", [])

    if not isinstance(filters_raw, list):
        _validation("filters", "invalid_type")
    if not isinstance(aggregations_raw, list):
        _validation("aggregations", "invalid_type")
    if not isinstance(order_by_raw, list):
        _validation("order_by", "invalid_type")

    has_projection = len(projection) > 0
    has_aggregations = len(aggregations_raw) > 0

    if has_projection and has_aggregations:
        _validation("mode", "detail_aggregate_mutex")
    if not has_projection and not has_aggregations:
        _validation("projection", "required_for_detail")

    if has_projection:
        _validate_projection(projection, allowed_fields)

    filters = _validate_filters(filters_raw, allowed_fields)
    aggregations = _validate_aggregations(aggregations_raw, allowed_fields)
    group_by_t = _validate_group_by(group_by, allowed_fields)
    order_by = _validate_order_by(
        order_by_raw,
        projection=tuple(projection) if has_projection else (),
        group_by=group_by_t,
        aggregation_aliases=frozenset(a.alias for a in aggregations),
        detail_mode=has_projection,
    )

    limit = _validate_limit(
        payload.get("limit", default_limit),
        default_limit=default_limit,
        max_limit=max_limit,
        limit_provided="limit" in payload,
    )

    return QueryRequest(
        dataset_id=dataset_id,
        projection=tuple(projection),
        filters=tuple(filters),
        aggregations=tuple(aggregations),
        group_by=group_by_t,
        order_by=tuple(order_by),
        limit=limit,
    )


def _validation(field: str, reason: str) -> NoReturn:
    raise DomainRuleError(
        "query request validation failed",
        code=ErrorCode.VALIDATION_ERROR,
        context={"field": field, "reason": reason},
    )


def _unsupported(field_id: str, operator: str) -> NoReturn:
    raise DomainRuleError(
        "operator is not supported",
        code=ErrorCode.UNSUPPORTED_OPERATOR,
        context={"field_id": field_id, "operator": operator},
    )


def _as_str_list(raw: object, field: str) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        _validation(field, "invalid_type")
    out: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item:
            _validation(field, "invalid_item")
        out.append(item)
    return out


def _validate_projection(
    projection: list[str], allowed_fields: Mapping[str, FieldRuleMeta]
) -> None:
    if len(projection) > _MAX_PROJECTION:
        _validation("projection", "max_items")
    seen: set[str] = set()
    for field_id in projection:
        if field_id in seen:
            _validation("projection", "duplicate")
        seen.add(field_id)
        if field_id not in allowed_fields:
            _validation("field_id", "unknown_field")


def _validate_filters(
    filters_raw: list[object], allowed_fields: Mapping[str, FieldRuleMeta]
) -> list[FilterSpec]:
    if len(filters_raw) > _MAX_FILTERS:
        _validation("filters", "max_items")
    out: list[FilterSpec] = []
    for item in filters_raw:
        if not isinstance(item, Mapping):
            _validation("filters", "invalid_item")
        field_id = item.get("field_id")
        if not isinstance(field_id, str) or not field_id:
            _validation("field_id", "required")
        if field_id not in allowed_fields:
            _validation("field_id", "unknown_field")
        meta = allowed_fields[field_id]
        if not meta.filterable:
            _validation("field_id", "not_filterable")

        op_raw = item.get("operator")
        if not isinstance(op_raw, str):
            _validation("operator", "invalid_type")
        try:
            operator = FilterOperator(op_raw)
        except ValueError:
            _unsupported(field_id, str(op_raw))

        if operator in _NULL_OPS:
            if "value" in item:
                _validation("value", "must_be_absent")
            out.append(
                FilterSpec(field_id=field_id, operator=operator, value=None)
            )
            continue

        if "value" not in item:
            _validation("value", "required")
        value = item["value"]

        if operator in _COMPARISON_OPS:
            if isinstance(value, (list, tuple, dict)):
                _validation("value", "must_be_scalar")
            _validate_scalar_value(value, meta.value_type, field="value")
            out.append(
                FilterSpec(field_id=field_id, operator=operator, value=value)
            )
            continue

        if operator is FilterOperator.IN:
            if not isinstance(value, list):
                _validation("value", "must_be_array")
            if len(value) < 1 or len(value) > _MAX_IN_VALUES:
                _validation("value", "in_cardinality")
            for element in value:
                if isinstance(element, (list, tuple, dict)):
                    _validation("value", "nested_array_forbidden")
                _validate_scalar_value(element, meta.value_type, field="value")
            out.append(
                FilterSpec(field_id=field_id, operator=operator, value=tuple(value))
            )
            continue

        if operator is FilterOperator.BETWEEN:
            if not isinstance(value, list):
                _validation("value", "must_be_array")
            if len(value) != 2:
                _validation("value", "between_cardinality")
            left, right = value[0], value[1]
            _validate_scalar_value(left, meta.value_type, field="value")
            _validate_scalar_value(right, meta.value_type, field="value")
            if not _ordered_pair(left, right, meta.value_type):
                _validation("value", "between_order")
            out.append(
                FilterSpec(
                    field_id=field_id, operator=operator, value=(left, right)
                )
            )
            continue

        _unsupported(field_id, operator.value)

    return out


def _validate_aggregations(
    aggregations_raw: list[object], allowed_fields: Mapping[str, FieldRuleMeta]
) -> list[AggregationSpec]:
    if len(aggregations_raw) > _MAX_AGGREGATIONS:
        _validation("aggregations", "max_items")
    out: list[AggregationSpec] = []
    aliases: set[str] = set()
    for item in aggregations_raw:
        if not isinstance(item, Mapping):
            _validation("aggregations", "invalid_item")
        fn_raw = item.get("function")
        field_id = item.get("field_id")
        alias = item.get("alias")
        if not isinstance(fn_raw, str):
            _validation("function", "invalid_type")
        if not isinstance(field_id, str) or not field_id:
            _validation("field_id", "required")
        if not isinstance(alias, str) or not alias:
            _validation("alias", "required")
        if not _safe_alias(alias):
            _validation("alias", "invalid_identifier")
        if alias in aliases:
            _validation("alias", "duplicate")
        aliases.add(alias)
        if field_id not in allowed_fields:
            _validation("field_id", "unknown_field")
        meta = allowed_fields[field_id]
        if not meta.aggregatable:
            _validation("field_id", "not_aggregatable")
        try:
            function = AggregateFunction(fn_raw)
        except ValueError:
            _validation("function", "unsupported")

        if function in (AggregateFunction.SUM, AggregateFunction.AVG):
            if meta.value_type not in _NUMERIC_TYPES:
                _validation("field_id", "numeric_required")
        elif (
            function in (AggregateFunction.MIN, AggregateFunction.MAX)
            and meta.value_type not in _COMPARABLE_TYPES
        ):
            _validation("field_id", "comparable_required")

        out.append(
            AggregationSpec(function=function, field_id=field_id, alias=alias)
        )
    return out


def _validate_group_by(
    group_by: list[str],
    allowed_fields: Mapping[str, FieldRuleMeta],
) -> tuple[str, ...]:
    if len(group_by) > _MAX_GROUP_BY:
        _validation("group_by", "max_items")
    seen: set[str] = set()
    for field_id in group_by:
        if field_id in seen:
            _validation("group_by", "duplicate")
        seen.add(field_id)
        if field_id not in allowed_fields:
            _validation("field_id", "unknown_field")
        if not allowed_fields[field_id].aggregatable:
            _validation("field_id", "not_aggregatable")
    return tuple(group_by)


def _validate_order_by(
    order_by_raw: list[object],
    *,
    projection: tuple[str, ...],
    group_by: tuple[str, ...],
    aggregation_aliases: frozenset[str],
    detail_mode: bool,
) -> list[OrderSpec]:
    if len(order_by_raw) > _MAX_ORDER_BY:
        _validation("order_by", "max_items")
    out: list[OrderSpec] = []
    seen_keys: set[str] = set()
    allowed_refs = (
        set(projection) if detail_mode else set(group_by) | set(aggregation_aliases)
    )
    for item in order_by_raw:
        if not isinstance(item, Mapping):
            _validation("order_by", "invalid_item")
        field_id = item.get("field_id")
        direction_raw = item.get("direction")
        if not isinstance(field_id, str) or not field_id:
            _validation("field_id", "required")
        if field_id in seen_keys:
            _validation("order_by", "duplicate")
        seen_keys.add(field_id)
        if field_id not in allowed_refs:
            _validation("order_by", "unknown_ref")
        if not isinstance(direction_raw, str):
            _validation("direction", "invalid_type")
        try:
            direction = SortDirection(direction_raw)
        except ValueError:
            _validation("direction", "unsupported")
        out.append(OrderSpec(field_id=field_id, direction=direction))
    return out


def _validate_limit(
    raw: object,
    *,
    default_limit: int,
    max_limit: int,
    limit_provided: bool,
) -> int:
    if not limit_provided:
        return default_limit
    if not isinstance(raw, int) or isinstance(raw, bool):
        _validation("limit", "invalid_type")
    if raw < 1:
        _validation("limit", "min")
    if raw > max_limit:
        raise DomainRuleError(
            "requested limit exceeds max_limit",
            code=ErrorCode.RESULT_LIMIT_EXCEEDED,
            context={"requested_limit": raw, "max_limit": max_limit},
        )
    return raw


def _validate_scalar_value(value: object, value_type: ValueType, *, field: str) -> None:
    if value_type is ValueType.STRING:
        if not isinstance(value, str):
            _validation(field, "type_mismatch")
        if len(value) > _MAX_STRING_LEN:
            _validation(field, "string_too_long")
        return
    if value_type is ValueType.INTEGER:
        if not isinstance(value, int) or isinstance(value, bool):
            _validation(field, "type_mismatch")
        return
    if value_type is ValueType.NUMBER:
        if not isinstance(value, str):
            _validation(field, "type_mismatch")
        lowered = value.strip().lower()
        if lowered in {"nan", "inf", "+inf", "-inf", "infinity", "+infinity", "-infinity"}:
            _validation(field, "non_finite")
        try:
            Decimal(value)
        except (InvalidOperation, ValueError):
            _validation(field, "invalid_decimal")
        return
    if value_type is ValueType.BOOLEAN:
        if not isinstance(value, bool):
            _validation(field, "type_mismatch")
        return
    if value_type is ValueType.DATE:
        if not isinstance(value, str) or not _DATE_RE.match(value):
            _validation(field, "invalid_date")
        try:
            date.fromisoformat(value)
        except ValueError:
            _validation(field, "invalid_date")
        return
    if value_type is ValueType.DATETIME:
        if not isinstance(value, str):
            _validation(field, "type_mismatch")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))  # noqa: FURB162
        except ValueError:
            _validation(field, "invalid_datetime")
        if parsed.tzinfo is None:
            _validation(field, "datetime_tz_required")
        return
    _validation(field, "unsupported_type")


def _ordered_pair(left: object, right: object, value_type: ValueType) -> bool:
    try:
        if value_type is ValueType.NUMBER:
            return Decimal(str(left)) <= Decimal(str(right))
        return cast(bool, left <= right)  # type: ignore[operator]
    except TypeError:
        return False


def _safe_alias(alias: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", alias))

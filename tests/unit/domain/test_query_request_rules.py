"""RED: QueryRequest §7.3 deterministic rules (Step 5.1).

Pure Domain validation. No MySQL / QueryPort / use case.
"""

from __future__ import annotations

from typing import Any, Mapping

import pytest

from enterprise_data_mcp.domain.errors import ErrorCode
from enterprise_data_mcp.domain.models import QueryRequest, ValueType

_DATASET = "sales_inventory_daily"
_DEFAULT_LIMIT = 50
_MAX_LIMIT = 100


def _rules() -> Any:
    """Import production module under test (must fail until 5.1-GREEN)."""
    import enterprise_data_mcp.domain.rules as rules_module

    return rules_module


def _field_meta(
    value_type: ValueType,
    *,
    filterable: bool = True,
    aggregatable: bool = True,
    sortable: bool = True,
) -> Any:
    rules = _rules()
    return rules.FieldRuleMeta(
        value_type=value_type,
        filterable=filterable,
        aggregatable=aggregatable,
        sortable=sortable,
    )


def _catalog() -> Mapping[str, Any]:
    return {
        "product_id": _field_meta(ValueType.STRING),
        "product_name": _field_meta(ValueType.STRING),
        "category": _field_meta(ValueType.STRING),
        "units_sold": _field_meta(ValueType.INTEGER),
        "gross_sales": _field_meta(ValueType.NUMBER),
        "business_date": _field_meta(ValueType.DATE),
        "ordered_at": _field_meta(ValueType.DATETIME),
        "flag": _field_meta(ValueType.BOOLEAN),
        "locked": _field_meta(
            ValueType.STRING, filterable=False, aggregatable=False, sortable=False
        ),
    }


def _validate(payload: Mapping[str, object], **kwargs: Any) -> QueryRequest:
    rules = _rules()
    return rules.validate_query_request(
        payload,
        allowed_fields=_catalog(),
        default_limit=kwargs.get("default_limit", _DEFAULT_LIMIT),
        max_limit=kwargs.get("max_limit", _MAX_LIMIT),
    )


def _assert_error(
    exc: BaseException,
    *,
    code: ErrorCode,
    allowed_context_keys: set[str],
) -> None:
    got = getattr(exc, "code", None)
    assert got in (code, code.value), f"expected {code}, got {got!r}"
    context = getattr(exc, "context", None)
    assert isinstance(context, dict)
    assert set(context.keys()) <= allowed_context_keys
    blob = f"{exc!s}{getattr(exc, 'message', '')}{context!s}"
    for banned in ("SELECT ", "INSERT ", "password", "mysql://"):
        assert banned not in blob


# ---------------------------------------------------------------------------
# Surface
# ---------------------------------------------------------------------------


def test_rules_module_exports_validate_and_error() -> None:
    rules = _rules()
    assert callable(getattr(rules, "validate_query_request", None))
    assert hasattr(rules, "DomainRuleError")
    assert hasattr(rules, "FieldRuleMeta")


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


def test_detail_mode_happy_path_preserves_order() -> None:
    req = _validate(
        {
            "dataset_id": _DATASET,
            "projection": ["product_name", "units_sold"],
            "filters": [
                {"field_id": "category", "operator": "EQ", "value": "A"},
                {"field_id": "units_sold", "operator": "GT", "value": 0},
            ],
            "aggregations": [],
            "group_by": [],
            "order_by": [{"field_id": "units_sold", "direction": "DESC"}],
            "limit": 20,
        }
    )
    assert isinstance(req, QueryRequest)
    assert req.projection == ("product_name", "units_sold")
    assert len(req.filters) == 2
    assert req.filters[0].field_id == "category"
    assert req.aggregations == ()
    assert req.limit == 20


def test_aggregate_mode_happy_path() -> None:
    req = _validate(
        {
            "dataset_id": _DATASET,
            "projection": [],
            "filters": [],
            "aggregations": [
                {
                    "function": "SUM",
                    "field_id": "gross_sales",
                    "alias": "total_sales",
                }
            ],
            "group_by": ["category"],
            "order_by": [{"field_id": "total_sales", "direction": "DESC"}],
            "limit": 10,
        }
    )
    assert req.projection == ()
    assert len(req.aggregations) == 1
    assert req.aggregations[0].alias == "total_sales"
    assert req.group_by == ("category",)


def test_omitted_limit_uses_default_limit() -> None:
    req = _validate(
        {
            "dataset_id": _DATASET,
            "projection": ["product_id"],
            "filters": [],
            "aggregations": [],
            "group_by": [],
            "order_by": [],
        }
    )
    assert req.limit == _DEFAULT_LIMIT


# ---------------------------------------------------------------------------
# Write intent / unknown fields
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("banned_key", ["raw_sql", "sql", "statement"])
def test_write_intent_forbidden_keys(banned_key: str) -> None:
    rules = _rules()
    payload: dict[str, object] = {
        "dataset_id": _DATASET,
        "projection": ["product_id"],
        "filters": [],
        "aggregations": [],
        "group_by": [],
        "order_by": [],
        "limit": 10,
        banned_key: "SELECT 1",
    }
    with pytest.raises(rules.DomainRuleError) as ei:
        _validate(payload)
    _assert_error(
        ei.value,
        code=ErrorCode.WRITE_OPERATION_FORBIDDEN,
        allowed_context_keys={"operation"},
    )


@pytest.mark.parametrize(
    "operation",
    ["INSERT", "UPDATE", "DELETE", "DDL", "DROP", "TRUNCATE"],
)
def test_write_operation_field_forbidden(operation: str) -> None:
    rules = _rules()
    payload = {
        "dataset_id": _DATASET,
        "projection": ["product_id"],
        "filters": [],
        "aggregations": [],
        "group_by": [],
        "order_by": [],
        "limit": 10,
        "operation": operation,
    }
    with pytest.raises(rules.DomainRuleError) as ei:
        _validate(payload)
    _assert_error(
        ei.value,
        code=ErrorCode.WRITE_OPERATION_FORBIDDEN,
        allowed_context_keys={"operation"},
    )


def test_unknown_top_level_field_is_validation_error() -> None:
    rules = _rules()
    payload = {
        "dataset_id": _DATASET,
        "projection": ["product_id"],
        "filters": [],
        "aggregations": [],
        "group_by": [],
        "order_by": [],
        "limit": 10,
        "join": "orders",
    }
    with pytest.raises(rules.DomainRuleError) as ei:
        _validate(payload)
    _assert_error(
        ei.value,
        code=ErrorCode.VALIDATION_ERROR,
        allowed_context_keys={"field", "reason"},
    )


# ---------------------------------------------------------------------------
# Projection / mode mutex
# ---------------------------------------------------------------------------


def test_detail_mode_requires_nonempty_projection() -> None:
    rules = _rules()
    with pytest.raises(rules.DomainRuleError) as ei:
        _validate(
            {
                "dataset_id": _DATASET,
                "projection": [],
                "filters": [],
                "aggregations": [],
                "group_by": [],
                "order_by": [],
                "limit": 10,
            }
        )
    _assert_error(
        ei.value,
        code=ErrorCode.VALIDATION_ERROR,
        allowed_context_keys={"field", "reason"},
    )


def test_projection_rejects_duplicates_and_over_20() -> None:
    rules = _rules()
    with pytest.raises(rules.DomainRuleError) as ei:
        _validate(
            {
                "dataset_id": _DATASET,
                "projection": ["product_id", "product_id"],
                "filters": [],
                "aggregations": [],
                "group_by": [],
                "order_by": [],
                "limit": 10,
            }
        )
    _assert_error(
        ei.value,
        code=ErrorCode.VALIDATION_ERROR,
        allowed_context_keys={"field", "reason"},
    )

    # >20 unique ids → VALIDATION_ERROR (count and/or unknown field_id).
    fields_21 = [f"product_id_{i}" for i in range(21)]
    with pytest.raises(rules.DomainRuleError) as ei2:
        _validate(
            {
                "dataset_id": _DATASET,
                "projection": fields_21,
                "filters": [],
                "aggregations": [],
                "group_by": [],
                "order_by": [],
                "limit": 10,
            }
        )
    _assert_error(
        ei2.value,
        code=ErrorCode.VALIDATION_ERROR,
        allowed_context_keys={"field", "reason"},
    )


def test_mode_mutex_rejects_mixed_projection_and_aggregations() -> None:
    rules = _rules()
    with pytest.raises(rules.DomainRuleError) as ei:
        _validate(
            {
                "dataset_id": _DATASET,
                "projection": ["product_id"],
                "filters": [],
                "aggregations": [
                    {
                        "function": "COUNT",
                        "field_id": "product_id",
                        "alias": "cnt",
                    }
                ],
                "group_by": [],
                "order_by": [],
                "limit": 10,
            }
        )
    _assert_error(
        ei.value,
        code=ErrorCode.VALIDATION_ERROR,
        allowed_context_keys={"field", "reason"},
    )


# ---------------------------------------------------------------------------
# Filters / operators / value shapes
# ---------------------------------------------------------------------------


def test_filters_max_20_and_unknown_field_validation_error() -> None:
    rules = _rules()
    many = [
        {"field_id": "units_sold", "operator": "EQ", "value": i} for i in range(21)
    ]
    with pytest.raises(rules.DomainRuleError) as ei:
        _validate(
            {
                "dataset_id": _DATASET,
                "projection": ["product_id"],
                "filters": many,
                "aggregations": [],
                "group_by": [],
                "order_by": [],
                "limit": 10,
            }
        )
    _assert_error(
        ei.value,
        code=ErrorCode.VALIDATION_ERROR,
        allowed_context_keys={"field", "reason"},
    )

    with pytest.raises(rules.DomainRuleError) as ei2:
        _validate(
            {
                "dataset_id": _DATASET,
                "projection": ["product_id"],
                "filters": [
                    {"field_id": "not_authorized", "operator": "EQ", "value": "x"}
                ],
                "aggregations": [],
                "group_by": [],
                "order_by": [],
                "limit": 10,
            }
        )
    _assert_error(
        ei2.value,
        code=ErrorCode.VALIDATION_ERROR,
        allowed_context_keys={"field", "reason"},
    )


def test_in_between_null_value_shapes() -> None:
    rules = _rules()
    # IN empty → VALIDATION_ERROR
    with pytest.raises(rules.DomainRuleError) as ei:
        _validate(
            {
                "dataset_id": _DATASET,
                "projection": ["product_id"],
                "filters": [{"field_id": "category", "operator": "IN", "value": []}],
                "aggregations": [],
                "group_by": [],
                "order_by": [],
                "limit": 10,
            }
        )
    _assert_error(
        ei.value,
        code=ErrorCode.VALIDATION_ERROR,
        allowed_context_keys={"field", "reason"},
    )

    # BETWEEN wrong arity
    with pytest.raises(rules.DomainRuleError) as ei2:
        _validate(
            {
                "dataset_id": _DATASET,
                "projection": ["business_date"],
                "filters": [
                    {
                        "field_id": "business_date",
                        "operator": "BETWEEN",
                        "value": ["2026-01-01"],
                    }
                ],
                "aggregations": [],
                "group_by": [],
                "order_by": [],
                "limit": 10,
            }
        )
    _assert_error(
        ei2.value,
        code=ErrorCode.VALIDATION_ERROR,
        allowed_context_keys={"field", "reason"},
    )

    # IS_NULL must not carry value
    with pytest.raises(rules.DomainRuleError) as ei3:
        _validate(
            {
                "dataset_id": _DATASET,
                "projection": ["product_id"],
                "filters": [
                    {
                        "field_id": "category",
                        "operator": "IS_NULL",
                        "value": "nope",
                    }
                ],
                "aggregations": [],
                "group_by": [],
                "order_by": [],
                "limit": 10,
            }
        )
    _assert_error(
        ei3.value,
        code=ErrorCode.VALIDATION_ERROR,
        allowed_context_keys={"field", "reason"},
    )


def test_unsupported_operator_and_non_filterable_field() -> None:
    rules = _rules()
    with pytest.raises(rules.DomainRuleError) as ei:
        _validate(
            {
                "dataset_id": _DATASET,
                "projection": ["product_id"],
                "filters": [
                    {"field_id": "category", "operator": "LIKE", "value": "%a%"}
                ],
                "aggregations": [],
                "group_by": [],
                "order_by": [],
                "limit": 10,
            }
        )
    _assert_error(
        ei.value,
        code=ErrorCode.UNSUPPORTED_OPERATOR,
        allowed_context_keys={"field_id", "operator"},
    )

    with pytest.raises(rules.DomainRuleError) as ei2:
        _validate(
            {
                "dataset_id": _DATASET,
                "projection": ["product_id"],
                "filters": [{"field_id": "locked", "operator": "EQ", "value": "x"}],
                "aggregations": [],
                "group_by": [],
                "order_by": [],
                "limit": 10,
            }
        )
    # non-filterable → UNSUPPORTED_OPERATOR or VALIDATION_ERROR; PLAN lists UNSUPPORTED for ops
    code = getattr(ei2.value, "code", None)
    assert code in (
        ErrorCode.UNSUPPORTED_OPERATOR,
        ErrorCode.UNSUPPORTED_OPERATOR.value,
        ErrorCode.VALIDATION_ERROR,
        ErrorCode.VALIDATION_ERROR.value,
    )


def test_string_length_and_number_shapes() -> None:
    rules = _rules()
    with pytest.raises(rules.DomainRuleError) as ei:
        _validate(
            {
                "dataset_id": _DATASET,
                "projection": ["product_name"],
                "filters": [
                    {
                        "field_id": "product_name",
                        "operator": "EQ",
                        "value": "x" * 257,
                    }
                ],
                "aggregations": [],
                "group_by": [],
                "order_by": [],
                "limit": 10,
            }
        )
    _assert_error(
        ei.value,
        code=ErrorCode.VALIDATION_ERROR,
        allowed_context_keys={"field", "reason"},
    )

    with pytest.raises(rules.DomainRuleError) as ei2:
        _validate(
            {
                "dataset_id": _DATASET,
                "projection": ["gross_sales"],
                "filters": [
                    {
                        "field_id": "gross_sales",
                        "operator": "EQ",
                        "value": "NaN",
                    }
                ],
                "aggregations": [],
                "group_by": [],
                "order_by": [],
                "limit": 10,
            }
        )
    _assert_error(
        ei2.value,
        code=ErrorCode.VALIDATION_ERROR,
        allowed_context_keys={"field", "reason"},
    )


# ---------------------------------------------------------------------------
# Aggregations / group_by / order_by
# ---------------------------------------------------------------------------


def test_aggregations_alias_unique_and_sum_requires_numeric() -> None:
    rules = _rules()
    with pytest.raises(rules.DomainRuleError) as ei:
        _validate(
            {
                "dataset_id": _DATASET,
                "projection": [],
                "filters": [],
                "aggregations": [
                    {
                        "function": "SUM",
                        "field_id": "units_sold",
                        "alias": "dup",
                    },
                    {
                        "function": "AVG",
                        "field_id": "gross_sales",
                        "alias": "dup",
                    },
                ],
                "group_by": [],
                "order_by": [],
                "limit": 10,
            }
        )
    _assert_error(
        ei.value,
        code=ErrorCode.VALIDATION_ERROR,
        allowed_context_keys={"field", "reason"},
    )

    with pytest.raises(rules.DomainRuleError) as ei2:
        _validate(
            {
                "dataset_id": _DATASET,
                "projection": [],
                "filters": [],
                "aggregations": [
                    {
                        "function": "SUM",
                        "field_id": "product_name",
                        "alias": "bad_sum",
                    }
                ],
                "group_by": [],
                "order_by": [],
                "limit": 10,
            }
        )
    _assert_error(
        ei2.value,
        code=ErrorCode.VALIDATION_ERROR,
        allowed_context_keys={"field", "reason"},
    )


def test_group_by_and_order_by_limits_and_duplicates() -> None:
    rules = _rules()
    with pytest.raises(rules.DomainRuleError) as ei:
        _validate(
            {
                "dataset_id": _DATASET,
                "projection": [],
                "filters": [],
                "aggregations": [
                    {
                        "function": "COUNT",
                        "field_id": "product_id",
                        "alias": "cnt",
                    }
                ],
                "group_by": [
                    "category",
                    "product_id",
                    "product_name",
                    "business_date",
                    "flag",
                    "units_sold",
                ],
                "order_by": [],
                "limit": 10,
            }
        )
    _assert_error(
        ei.value,
        code=ErrorCode.VALIDATION_ERROR,
        allowed_context_keys={"field", "reason"},
    )

    with pytest.raises(rules.DomainRuleError) as ei2:
        _validate(
            {
                "dataset_id": _DATASET,
                "projection": ["product_id", "units_sold"],
                "filters": [],
                "aggregations": [],
                "group_by": [],
                "order_by": [
                    {"field_id": "units_sold", "direction": "ASC"},
                    {"field_id": "units_sold", "direction": "DESC"},
                ],
                "limit": 10,
            }
        )
    _assert_error(
        ei2.value,
        code=ErrorCode.VALIDATION_ERROR,
        allowed_context_keys={"field", "reason"},
    )


# ---------------------------------------------------------------------------
# Limit
# ---------------------------------------------------------------------------


def test_limit_less_than_one_validation_error() -> None:
    rules = _rules()
    with pytest.raises(rules.DomainRuleError) as ei:
        _validate(
            {
                "dataset_id": _DATASET,
                "projection": ["product_id"],
                "filters": [],
                "aggregations": [],
                "group_by": [],
                "order_by": [],
                "limit": 0,
            }
        )
    _assert_error(
        ei.value,
        code=ErrorCode.VALIDATION_ERROR,
        allowed_context_keys={"field", "reason"},
    )


def test_limit_above_max_is_result_limit_exceeded() -> None:
    rules = _rules()
    with pytest.raises(rules.DomainRuleError) as ei:
        _validate(
            {
                "dataset_id": _DATASET,
                "projection": ["product_id"],
                "filters": [],
                "aggregations": [],
                "group_by": [],
                "order_by": [],
                "limit": 101,
            },
            max_limit=100,
        )
    _assert_error(
        ei.value,
        code=ErrorCode.RESULT_LIMIT_EXCEEDED,
        allowed_context_keys={"requested_limit", "max_limit"},
    )


def test_rules_stay_pure_no_io_imports() -> None:
    import ast
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "enterprise_data_mcp"
        / "domain"
        / "rules.py"
    )
    assert path.is_file(), "expected domain/rules.py (GREEN deliverable)"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    forbidden = (
        "enterprise_data_mcp.adapters",
        "enterprise_data_mcp.application",
        "enterprise_data_mcp.hosts",
        "yaml",
        "pydantic",
        "mysql",
        "fastmcp",
        "sqlite3",
    )
    violations = [
        name
        for name in imported
        if any(name == p or name.startswith(p + ".") for p in forbidden)
    ]
    assert not violations, f"rules.py forbidden imports: {violations}"


# ---------------------------------------------------------------------------
# QA-02 coverage matrix (branch gaps)
# ---------------------------------------------------------------------------


def _detail_base(**overrides: Any) -> dict[str, object]:
    payload: dict[str, object] = {
        "dataset_id": _DATASET,
        "projection": ["product_id"],
        "filters": [],
        "aggregations": [],
        "group_by": [],
        "order_by": [],
        "limit": 10,
    }
    payload.update(overrides)
    return payload


def _agg_base(**overrides: Any) -> dict[str, object]:
    payload: dict[str, object] = {
        "dataset_id": _DATASET,
        "projection": [],
        "filters": [],
        "aggregations": [
            {"function": "COUNT", "field_id": "product_id", "alias": "cnt"}
        ],
        "group_by": ["category"],
        "order_by": [],
        "limit": 10,
    }
    payload.update(overrides)
    return payload


def test_non_mapping_payload_is_validation_error() -> None:
    rules = _rules()
    with pytest.raises(rules.DomainRuleError) as ei:
        rules.validate_query_request(
            ["not", "a", "mapping"],  # type: ignore[arg-type]
            allowed_fields=_catalog(),
            default_limit=_DEFAULT_LIMIT,
            max_limit=_MAX_LIMIT,
        )
    _assert_error(
        ei.value,
        code=ErrorCode.VALIDATION_ERROR,
        allowed_context_keys={"field", "reason"},
    )
    assert ei.value.context.get("field") == "payload"


@pytest.mark.parametrize("dataset_id", [None, "", 123, True])
def test_bad_dataset_id_required(dataset_id: object) -> None:
    rules = _rules()
    with pytest.raises(rules.DomainRuleError) as ei:
        _validate(_detail_base(dataset_id=dataset_id))
    _assert_error(
        ei.value,
        code=ErrorCode.VALIDATION_ERROR,
        allowed_context_keys={"field", "reason"},
    )
    assert ei.value.context.get("field") == "dataset_id"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("filters", {"field_id": "category"}),
        ("aggregations", {"function": "COUNT"}),
        ("order_by", {"field_id": "product_id"}),
    ],
)
def test_top_level_list_fields_reject_non_list(field: str, value: object) -> None:
    rules = _rules()
    with pytest.raises(rules.DomainRuleError) as ei:
        _validate(_detail_base(**{field: value}))
    _assert_error(
        ei.value,
        code=ErrorCode.VALIDATION_ERROR,
        allowed_context_keys={"field", "reason"},
    )
    assert ei.value.context.get("field") == field
    assert ei.value.context.get("reason") == "invalid_type"


@pytest.mark.parametrize("field", ["projection", "group_by"])
@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        (None, None),  # None → empty list, then other validation may fire
        ({"a": 1}, "invalid_type"),
        (["product_id", ""], "invalid_item"),
        (["product_id", 1], "invalid_item"),
    ],
)
def test_projection_group_by_as_str_list_shapes(
    field: str, raw: object, reason: str | None
) -> None:
    rules = _rules()
    if field == "projection":
        if raw is None:
            # None projection → [] → required_for_detail when no aggregations
            with pytest.raises(rules.DomainRuleError) as ei:
                _validate(_detail_base(projection=None))
            assert ei.value.context.get("field") in {"projection", "mode"}
            return
        with pytest.raises(rules.DomainRuleError) as ei:
            _validate(_detail_base(projection=raw))
    else:
        if raw is None:
            req = _validate(_agg_base(group_by=None))
            assert req.group_by == ()
            return
        with pytest.raises(rules.DomainRuleError) as ei:
            _validate(_agg_base(group_by=raw))
    _assert_error(
        ei.value,
        code=ErrorCode.VALIDATION_ERROR,
        allowed_context_keys={"field", "reason"},
    )
    if reason is not None:
        assert ei.value.context.get("reason") == reason


def test_optional_non_write_operation_is_allowed() -> None:
    req = _validate(_detail_base(operation="READ"))
    assert req.dataset_id == _DATASET
    req2 = _validate(_detail_base(operation="query"))
    assert req2.limit == 10
    req3 = _validate(_detail_base(operation=None))
    assert req3.projection == ("product_id",)


def test_projection_unknown_field() -> None:
    rules = _rules()
    with pytest.raises(rules.DomainRuleError) as ei:
        _validate(_detail_base(projection=["not_a_field"]))
    _assert_error(
        ei.value,
        code=ErrorCode.VALIDATION_ERROR,
        allowed_context_keys={"field", "reason"},
    )
    assert ei.value.context.get("reason") == "unknown_field"


@pytest.mark.parametrize(
    ("filters", "field", "reason"),
    [
        (["not-a-mapping"], "filters", "invalid_item"),
        ([{"operator": "EQ", "value": "x"}], "field_id", "required"),
        ([{"field_id": "", "operator": "EQ", "value": "x"}], "field_id", "required"),
        (
            [{"field_id": "category", "operator": 1, "value": "x"}],
            "operator",
            "invalid_type",
        ),
        (
            [{"field_id": "category", "operator": "EQ"}],
            "value",
            "required",
        ),
        (
            [{"field_id": "category", "operator": "EQ", "value": ["a"]}],
            "value",
            "must_be_scalar",
        ),
        (
            [{"field_id": "category", "operator": "EQ", "value": {"k": "v"}}],
            "value",
            "must_be_scalar",
        ),
    ],
)
def test_filter_error_matrix(
    filters: list[object], field: str, reason: str
) -> None:
    rules = _rules()
    with pytest.raises(rules.DomainRuleError) as ei:
        _validate(_detail_base(filters=filters))
    _assert_error(
        ei.value,
        code=ErrorCode.VALIDATION_ERROR,
        allowed_context_keys={"field", "reason"},
    )
    assert ei.value.context.get("field") == field
    assert ei.value.context.get("reason") == reason


@pytest.mark.parametrize("operator", ["IS_NULL", "IS_NOT_NULL"])
def test_null_ops_success_without_value(operator: str) -> None:
    req = _validate(
        _detail_base(
            filters=[{"field_id": "category", "operator": operator}],
        )
    )
    assert len(req.filters) == 1
    assert req.filters[0].operator.value == operator
    assert req.filters[0].value is None


def test_in_success_and_nested_and_non_list() -> None:
    rules = _rules()
    req = _validate(
        _detail_base(
            filters=[
                {
                    "field_id": "category",
                    "operator": "IN",
                    "value": ["A", "B"],
                }
            ]
        )
    )
    assert req.filters[0].value == ("A", "B")

    with pytest.raises(rules.DomainRuleError) as ei:
        _validate(
            _detail_base(
                filters=[
                    {
                        "field_id": "category",
                        "operator": "IN",
                        "value": "A",
                    }
                ]
            )
        )
    assert ei.value.context.get("reason") == "must_be_array"

    with pytest.raises(rules.DomainRuleError) as ei2:
        _validate(
            _detail_base(
                filters=[
                    {
                        "field_id": "category",
                        "operator": "IN",
                        "value": [["nested"]],
                    }
                ]
            )
        )
    assert ei2.value.context.get("reason") == "nested_array_forbidden"


def test_between_success_and_order_reverse() -> None:
    rules = _rules()
    req = _validate(
        _detail_base(
            projection=["business_date"],
            filters=[
                {
                    "field_id": "business_date",
                    "operator": "BETWEEN",
                    "value": ["2026-01-01", "2026-12-31"],
                }
            ],
        )
    )
    assert req.filters[0].value == ("2026-01-01", "2026-12-31")

    with pytest.raises(rules.DomainRuleError) as ei:
        _validate(
            _detail_base(
                projection=["business_date"],
                filters=[
                    {
                        "field_id": "business_date",
                        "operator": "BETWEEN",
                        "value": ["2026-12-31", "2026-01-01"],
                    }
                ],
            )
        )
    assert ei.value.context.get("reason") == "between_order"

    with pytest.raises(rules.DomainRuleError) as ei2:
        _validate(
            _detail_base(
                projection=["units_sold"],
                filters=[
                    {
                        "field_id": "units_sold",
                        "operator": "BETWEEN",
                        "value": "1-2",
                    }
                ],
            )
        )
    assert ei2.value.context.get("reason") == "must_be_array"


@pytest.mark.parametrize(
    ("aggregations", "field", "reason"),
    [
        (
            [
                {
                    "function": "COUNT",
                    "field_id": "product_id",
                    "alias": f"a{i}",
                }
                for i in range(11)
            ],
            "aggregations",
            "max_items",
        ),
        (["not-mapping"], "aggregations", "invalid_item"),
        (
            [{"function": 1, "field_id": "product_id", "alias": "a"}],
            "function",
            "invalid_type",
        ),
        (
            [{"function": "COUNT", "field_id": "", "alias": "a"}],
            "field_id",
            "required",
        ),
        (
            [{"function": "COUNT", "field_id": "product_id", "alias": ""}],
            "alias",
            "required",
        ),
        (
            [{"function": "COUNT", "field_id": "product_id", "alias": "bad-alias"}],
            "alias",
            "invalid_identifier",
        ),
        (
            [{"function": "COUNT", "field_id": "missing", "alias": "a"}],
            "field_id",
            "unknown_field",
        ),
        (
            [{"function": "COUNT", "field_id": "locked", "alias": "a"}],
            "field_id",
            "not_aggregatable",
        ),
        (
            [{"function": "MEDIAN", "field_id": "units_sold", "alias": "a"}],
            "function",
            "unsupported",
        ),
    ],
)
def test_aggregations_error_matrix(
    aggregations: list[object], field: str, reason: str
) -> None:
    rules = _rules()
    with pytest.raises(rules.DomainRuleError) as ei:
        _validate(_agg_base(aggregations=aggregations, group_by=[], order_by=[]))
    _assert_error(
        ei.value,
        code=ErrorCode.VALIDATION_ERROR,
        allowed_context_keys={"field", "reason"},
    )
    assert ei.value.context.get("field") == field
    assert ei.value.context.get("reason") == reason


def test_min_max_comparable_and_avg_ok() -> None:
    req = _validate(
        _agg_base(
            aggregations=[
                {"function": "MIN", "field_id": "product_name", "alias": "mn"},
                {"function": "MAX", "field_id": "business_date", "alias": "mx"},
                {"function": "AVG", "field_id": "gross_sales", "alias": "avg_g"},
            ],
            group_by=["category"],
            order_by=[{"field_id": "avg_g", "direction": "ASC"}],
        )
    )
    assert len(req.aggregations) == 3


@pytest.mark.parametrize(
    ("group_by", "field", "reason"),
    [
        (["category", "category"], "group_by", "duplicate"),
        (["nope"], "field_id", "unknown_field"),
        (["locked"], "field_id", "not_aggregatable"),
    ],
)
def test_group_by_error_matrix(
    group_by: list[str], field: str, reason: str
) -> None:
    rules = _rules()
    with pytest.raises(rules.DomainRuleError) as ei:
        _validate(_agg_base(group_by=group_by))
    _assert_error(
        ei.value,
        code=ErrorCode.VALIDATION_ERROR,
        allowed_context_keys={"field", "reason"},
    )
    assert ei.value.context.get("field") == field
    assert ei.value.context.get("reason") == reason


@pytest.mark.parametrize(
    ("order_by", "field", "reason"),
    [
        (
            [
                {"field_id": f, "direction": "ASC"}
                for f in (
                    "product_id",
                    "product_name",
                    "category",
                    "units_sold",
                    "gross_sales",
                    "flag",
                )
            ],
            "order_by",
            "max_items",
        ),
        (["not-mapping"], "order_by", "invalid_item"),
        ([{"direction": "ASC"}], "field_id", "required"),
        (
            [{"field_id": "category", "direction": "ASC"}],
            "order_by",
            "unknown_ref",
        ),
        (
            [{"field_id": "product_id", "direction": 1}],
            "direction",
            "invalid_type",
        ),
        (
            [{"field_id": "product_id", "direction": "SIDEWAYS"}],
            "direction",
            "unsupported",
        ),
    ],
)
def test_order_by_error_matrix(
    order_by: list[object], field: str, reason: str
) -> None:
    rules = _rules()
    projection = [
        "product_id",
        "product_name",
        "category",
        "units_sold",
        "gross_sales",
        "flag",
    ]
    # unknown_ref case keeps single-field projection so category is not allowed
    if reason == "unknown_ref":
        projection = ["product_id"]
    elif reason == "max_items":
        pass
    else:
        projection = ["product_id"]
    with pytest.raises(rules.DomainRuleError) as ei:
        _validate(_detail_base(projection=projection, order_by=order_by))
    _assert_error(
        ei.value,
        code=ErrorCode.VALIDATION_ERROR,
        allowed_context_keys={"field", "reason"},
    )
    assert ei.value.context.get("field") == field
    assert ei.value.context.get("reason") == reason


@pytest.mark.parametrize("limit", [True, "10", 10.5, None])
def test_limit_invalid_types(limit: object) -> None:
    rules = _rules()
    with pytest.raises(rules.DomainRuleError) as ei:
        _validate(_detail_base(limit=limit))
    _assert_error(
        ei.value,
        code=ErrorCode.VALIDATION_ERROR,
        allowed_context_keys={"field", "reason"},
    )
    assert ei.value.context.get("field") == "limit"
    assert ei.value.context.get("reason") == "invalid_type"


@pytest.mark.parametrize(
    ("field_id", "value"),
    [
        ("product_name", "ok"),
        ("units_sold", 42),
        ("gross_sales", "12.5"),
        ("flag", True),
        ("business_date", "2026-03-15"),
        ("ordered_at", "2026-03-15T12:00:00Z"),
        ("ordered_at", "2026-03-15T12:00:00+08:00"),
    ],
)
def test_scalar_success_paths(field_id: str, value: object) -> None:
    req = _validate(
        _detail_base(
            projection=[field_id],
            filters=[{"field_id": field_id, "operator": "EQ", "value": value}],
        )
    )
    assert req.filters[0].value == value


@pytest.mark.parametrize(
    ("field_id", "value", "reason"),
    [
        ("product_name", 1, "type_mismatch"),
        ("units_sold", "1", "type_mismatch"),
        ("units_sold", True, "type_mismatch"),
        ("gross_sales", 1.2, "type_mismatch"),
        ("gross_sales", "not-a-decimal", "invalid_decimal"),
        ("gross_sales", "Infinity", "non_finite"),
        ("flag", "true", "type_mismatch"),
        ("business_date", "2026/01/01", "invalid_date"),
        ("business_date", "2026-13-40", "invalid_date"),
        ("ordered_at", 123, "type_mismatch"),
        ("ordered_at", "not-a-dt", "invalid_datetime"),
        ("ordered_at", "2026-03-15T12:00:00", "datetime_tz_required"),
    ],
)
def test_scalar_mismatch_paths(
    field_id: str, value: object, reason: str
) -> None:
    rules = _rules()
    with pytest.raises(rules.DomainRuleError) as ei:
        _validate(
            _detail_base(
                projection=[field_id],
                filters=[{"field_id": field_id, "operator": "EQ", "value": value}],
            )
        )
    _assert_error(
        ei.value,
        code=ErrorCode.VALIDATION_ERROR,
        allowed_context_keys={"field", "reason"},
    )
    assert ei.value.context.get("reason") == reason


def test_number_between_order_and_in_cardinality_over_max() -> None:
    rules = _rules()
    req = _validate(
        _detail_base(
            projection=["gross_sales"],
            filters=[
                {
                    "field_id": "gross_sales",
                    "operator": "BETWEEN",
                    "value": ["1.0", "2.0"],
                }
            ],
        )
    )
    assert req.filters[0].value == ("1.0", "2.0")

    with pytest.raises(rules.DomainRuleError) as ei:
        _validate(
            _detail_base(
                filters=[
                    {
                        "field_id": "category",
                        "operator": "IN",
                        "value": [f"v{i}" for i in range(101)],
                    }
                ]
            )
        )
    assert ei.value.context.get("reason") == "in_cardinality"

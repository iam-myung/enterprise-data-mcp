"""RED: ErrorCode + domain enums (SPEC §7.2 / API §7 / Step 2.2)."""

from __future__ import annotations

from enum import Enum
from typing import Any

import pytest

# Exact closures from API §7 / SPEC §7.2 — named constants, no invented codes.
EXPECTED_ERROR_CODES: frozenset[str] = frozenset(
    {
        "VALIDATION_ERROR",
        "DATASET_NOT_ALLOWED",
        "FIELD_NOT_ALLOWED",
        "WRITE_OPERATION_FORBIDDEN",
        "UNSUPPORTED_OPERATOR",
        "RESULT_LIMIT_EXCEEDED",
        "QUERY_TIMEOUT",
        "DATA_SOURCE_UNAVAILABLE",
        "AUDIT_UNAVAILABLE",
        "TRANSPORT_ERROR",
        "INTERNAL_ERROR",
    }
)

EXPECTED_TRANSPORT_KIND: frozenset[str] = frozenset({"STDIO", "SSE", "STREAMABLE_HTTP"})
EXPECTED_RESULT_STATUS: frozenset[str] = frozenset({"NON_EMPTY", "EMPTY"})
EXPECTED_AUDIT_STATUS: frozenset[str] = frozenset(
    {"STARTED", "SUCCEEDED", "REJECTED", "FAILED"}
)
EXPECTED_FILTER_OPERATOR: frozenset[str] = frozenset(
    {
        "EQ",
        "NE",
        "GT",
        "GTE",
        "LT",
        "LTE",
        "IN",
        "BETWEEN",
        "IS_NULL",
        "IS_NOT_NULL",
    }
)
EXPECTED_AGGREGATE_FUNCTION: frozenset[str] = frozenset(
    {"COUNT", "SUM", "AVG", "MIN", "MAX"}
)
EXPECTED_SORT_DIRECTION: frozenset[str] = frozenset({"ASC", "DESC"})


def _load_errors() -> Any:
    """Import production module under test (must fail until 2.2-GREEN)."""
    import enterprise_data_mcp.domain.errors as errors_module

    return errors_module


def _member_values(enum_cls: type[Enum]) -> frozenset[str]:
    return frozenset(member.value for member in enum_cls)


def test_error_code_is_str_enum_with_exact_api_closure() -> None:
    errors = _load_errors()
    ErrorCode = errors.ErrorCode

    assert issubclass(ErrorCode, str)
    assert issubclass(ErrorCode, Enum)
    assert _member_values(ErrorCode) == EXPECTED_ERROR_CODES
    assert len(ErrorCode) == 11
    assert ErrorCode.VALIDATION_ERROR.value == "VALIDATION_ERROR"
    assert ErrorCode.INTERNAL_ERROR == "INTERNAL_ERROR"


def test_error_code_rejects_unknown_member_name() -> None:
    errors = _load_errors()
    ErrorCode = errors.ErrorCode

    with pytest.raises(ValueError):
        ErrorCode("FAKE_ERROR_CODE")

    assert "FAKE_ERROR_CODE" not in _member_values(ErrorCode)
    assert "TEMPORARY_ADAPTER_ERROR" not in _member_values(ErrorCode)


def test_transport_kind_exact_closure() -> None:
    errors = _load_errors()
    TransportKind = errors.TransportKind

    assert issubclass(TransportKind, str)
    assert _member_values(TransportKind) == EXPECTED_TRANSPORT_KIND
    assert TransportKind.STREAMABLE_HTTP.value == "STREAMABLE_HTTP"


def test_result_status_exact_closure() -> None:
    errors = _load_errors()
    ResultStatus = errors.ResultStatus

    assert issubclass(ResultStatus, str)
    assert _member_values(ResultStatus) == EXPECTED_RESULT_STATUS


def test_audit_status_exact_closure() -> None:
    errors = _load_errors()
    AuditStatus = errors.AuditStatus

    assert issubclass(AuditStatus, str)
    assert _member_values(AuditStatus) == EXPECTED_AUDIT_STATUS


def test_filter_operator_exact_closure() -> None:
    errors = _load_errors()
    FilterOperator = errors.FilterOperator

    assert issubclass(FilterOperator, str)
    assert _member_values(FilterOperator) == EXPECTED_FILTER_OPERATOR
    assert FilterOperator.IS_NOT_NULL.value == "IS_NOT_NULL"


def test_aggregate_function_exact_closure() -> None:
    errors = _load_errors()
    AggregateFunction = errors.AggregateFunction

    assert issubclass(AggregateFunction, str)
    assert _member_values(AggregateFunction) == EXPECTED_AGGREGATE_FUNCTION


def test_sort_direction_exact_closure() -> None:
    errors = _load_errors()
    SortDirection = errors.SortDirection

    assert issubclass(SortDirection, str)
    assert _member_values(SortDirection) == EXPECTED_SORT_DIRECTION


def test_domain_enums_reject_invented_members() -> None:
    errors = _load_errors()

    with pytest.raises(ValueError):
        errors.FilterOperator("LIKE")
    with pytest.raises(ValueError):
        errors.AggregateFunction("COUNT_DISTINCT")
    with pytest.raises(ValueError):
        errors.TransportKind("WEBSOCKET")
    with pytest.raises(ValueError):
        errors.ResultStatus("PARTIAL")

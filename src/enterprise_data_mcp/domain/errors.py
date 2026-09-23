"""Domain ErrorCode and enums (SPEC §7.2 / API §7)."""

from __future__ import annotations

from enum import StrEnum


class ErrorCode(StrEnum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    DATASET_NOT_ALLOWED = "DATASET_NOT_ALLOWED"
    FIELD_NOT_ALLOWED = "FIELD_NOT_ALLOWED"
    WRITE_OPERATION_FORBIDDEN = "WRITE_OPERATION_FORBIDDEN"
    UNSUPPORTED_OPERATOR = "UNSUPPORTED_OPERATOR"
    RESULT_LIMIT_EXCEEDED = "RESULT_LIMIT_EXCEEDED"
    QUERY_TIMEOUT = "QUERY_TIMEOUT"
    DATA_SOURCE_UNAVAILABLE = "DATA_SOURCE_UNAVAILABLE"
    AUDIT_UNAVAILABLE = "AUDIT_UNAVAILABLE"
    TRANSPORT_ERROR = "TRANSPORT_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class TransportKind(StrEnum):
    STDIO = "STDIO"
    SSE = "SSE"
    STREAMABLE_HTTP = "STREAMABLE_HTTP"


class ResultStatus(StrEnum):
    NON_EMPTY = "NON_EMPTY"
    EMPTY = "EMPTY"


class AuditStatus(StrEnum):
    STARTED = "STARTED"
    SUCCEEDED = "SUCCEEDED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


class FilterOperator(StrEnum):
    EQ = "EQ"
    NE = "NE"
    GT = "GT"
    GTE = "GTE"
    LT = "LT"
    LTE = "LTE"
    IN = "IN"
    BETWEEN = "BETWEEN"
    IS_NULL = "IS_NULL"
    IS_NOT_NULL = "IS_NOT_NULL"


class AggregateFunction(StrEnum):
    COUNT = "COUNT"
    SUM = "SUM"
    AVG = "AVG"
    MIN = "MIN"
    MAX = "MAX"


class SortDirection(StrEnum):
    ASC = "ASC"
    DESC = "DESC"

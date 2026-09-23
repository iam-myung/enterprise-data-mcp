"""RED: Full ErrorCode closure hooked into release gate (API §7 / Step 14)."""

from __future__ import annotations

from enum import Enum
from typing import Any

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


def _gate() -> Any:
    import scripts.quality_gate as quality_gate

    return quality_gate


def test_release_gate_exports_exact_error_code_closure() -> None:
    gate = _gate()
    closure = frozenset(getattr(gate, "ERROR_CODE_CLOSURE"))
    assert closure == EXPECTED_ERROR_CODES
    assert len(closure) == 11


def test_release_gate_error_codes_match_domain_enum() -> None:
    from enterprise_data_mcp.domain.errors import ErrorCode

    gate = _gate()
    closure = frozenset(getattr(gate, "ERROR_CODE_CLOSURE"))
    domain = frozenset(m.value for m in ErrorCode)
    assert issubclass(ErrorCode, str) and issubclass(ErrorCode, Enum)
    assert domain == closure == EXPECTED_ERROR_CODES


def test_release_gate_rejects_invented_error_codes() -> None:
    gate = _gate()
    assert "FAKE_ERROR_CODE" not in frozenset(gate.ERROR_CODE_CLOSURE)
    assert "SUCCESS" not in frozenset(gate.ERROR_CODE_CLOSURE)

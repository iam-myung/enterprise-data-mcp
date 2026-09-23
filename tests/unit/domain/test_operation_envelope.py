"""RED: OperationEnvelope invariants (SPEC §7.1 / API §3 / Step 2.1)."""

from __future__ import annotations

from types import MappingProxyType
from typing import Any

import pytest

# Fixed meta fixture values — RFC3339 UTC sample, not tied to wall clock.
_TRACE_ID = "11111111-2222-3333-4444-555555555555"
_TIMESTAMP_UTC = "2026-09-13T09:00:00Z"
_OPERATION = "query_data"
_DURATION_MS = 12


def _load_models() -> tuple[Any, Any, Any]:
    """Import production symbols under test (must fail until 2.1-GREEN)."""
    from enterprise_data_mcp.domain.models import (
        EnvelopeMeta,
        ErrorInfo,
        OperationEnvelope,
    )

    return EnvelopeMeta, ErrorInfo, OperationEnvelope


def _meta(EnvelopeMeta: Any) -> Any:
    return EnvelopeMeta(
        trace_id=_TRACE_ID,
        timestamp_utc=_TIMESTAMP_UTC,
        operation=_OPERATION,
        duration_ms=_DURATION_MS,
    )


def _error(ErrorInfo: Any) -> Any:
    return ErrorInfo(
        code="VALIDATION_ERROR",
        message="sanitized message",
        context=MappingProxyType({"field": "limit", "reason": "too_small"}),
    )


def test_ok_factory_sets_success_data_and_null_error() -> None:
    EnvelopeMeta, ErrorInfo, OperationEnvelope = _load_models()
    payload = {"datasets": (), "count": 0}
    envelope = OperationEnvelope.ok(data=payload, meta=_meta(EnvelopeMeta))

    assert envelope.success is True
    assert envelope.data == payload
    assert envelope.error is None
    assert envelope.meta.trace_id == _TRACE_ID
    assert envelope.meta.timestamp_utc == _TIMESTAMP_UTC
    assert envelope.meta.operation == _OPERATION
    assert envelope.meta.duration_ms == _DURATION_MS


def test_fail_factory_sets_failure_error_and_null_data() -> None:
    EnvelopeMeta, ErrorInfo, OperationEnvelope = _load_models()
    err = _error(ErrorInfo)
    envelope = OperationEnvelope.fail(error=err, meta=_meta(EnvelopeMeta))

    assert envelope.success is False
    assert envelope.data is None
    assert envelope.error is err
    assert envelope.meta.operation == _OPERATION


def test_empty_payload_is_still_success_with_data() -> None:
    """Empty business payload remains success+data, never an error (API §3)."""
    EnvelopeMeta, ErrorInfo, OperationEnvelope = _load_models()
    envelope = OperationEnvelope.ok(data={}, meta=_meta(EnvelopeMeta))

    assert envelope.success is True
    assert envelope.data == {}
    assert envelope.error is None


def test_rejects_success_with_null_data() -> None:
    EnvelopeMeta, ErrorInfo, OperationEnvelope = _load_models()
    with pytest.raises(ValueError, match="data"):
        OperationEnvelope(success=True, data=None, error=None, meta=_meta(EnvelopeMeta))


def test_rejects_success_with_error_present() -> None:
    EnvelopeMeta, ErrorInfo, OperationEnvelope = _load_models()
    with pytest.raises(ValueError, match="error"):
        OperationEnvelope(
            success=True,
            data={"ok": True},
            error=_error(ErrorInfo),
            meta=_meta(EnvelopeMeta),
        )


def test_rejects_failure_with_null_error() -> None:
    EnvelopeMeta, ErrorInfo, OperationEnvelope = _load_models()
    with pytest.raises(ValueError, match="error"):
        OperationEnvelope(
            success=False,
            data=None,
            error=None,
            meta=_meta(EnvelopeMeta),
        )


def test_rejects_failure_with_data_present() -> None:
    EnvelopeMeta, ErrorInfo, OperationEnvelope = _load_models()
    with pytest.raises(ValueError, match="data"):
        OperationEnvelope(
            success=False,
            data={"leaked": True},
            error=_error(ErrorInfo),
            meta=_meta(EnvelopeMeta),
        )


def test_rejects_simultaneous_data_and_error() -> None:
    EnvelopeMeta, ErrorInfo, OperationEnvelope = _load_models()
    with pytest.raises(ValueError, match="mutual"):
        OperationEnvelope(
            success=True,
            data={"ok": True},
            error=_error(ErrorInfo),
            meta=_meta(EnvelopeMeta),
        )


def test_meta_fields_always_present_on_ok_and_fail() -> None:
    EnvelopeMeta, ErrorInfo, OperationEnvelope = _load_models()
    ok = OperationEnvelope.ok(data={"x": 1}, meta=_meta(EnvelopeMeta))
    fail = OperationEnvelope.fail(error=_error(ErrorInfo), meta=_meta(EnvelopeMeta))

    for envelope in (ok, fail):
        assert envelope.meta.trace_id
        assert envelope.meta.timestamp_utc
        assert envelope.meta.operation
        assert isinstance(envelope.meta.duration_ms, int)


def test_envelope_and_meta_are_immutable() -> None:
    EnvelopeMeta, ErrorInfo, OperationEnvelope = _load_models()
    envelope = OperationEnvelope.ok(data={"x": 1}, meta=_meta(EnvelopeMeta))

    with pytest.raises(AttributeError):
        envelope.success = False  # type: ignore[misc]

    with pytest.raises(AttributeError):
        envelope.meta.trace_id = "mutated"  # type: ignore[misc]

    with pytest.raises(AttributeError):
        envelope.error = _error(ErrorInfo)  # type: ignore[misc]


def test_error_info_is_immutable() -> None:
    EnvelopeMeta, ErrorInfo, OperationEnvelope = _load_models()
    err = _error(ErrorInfo)

    with pytest.raises(AttributeError):
        err.code = "INTERNAL_ERROR"  # type: ignore[misc]

    with pytest.raises(AttributeError):
        err.message = "changed"  # type: ignore[misc]

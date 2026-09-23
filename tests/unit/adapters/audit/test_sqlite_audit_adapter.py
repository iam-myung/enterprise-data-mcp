"""RED: SqliteAuditAdapter call_id state machine (SPEC §11.4 / Step 7.2).

Idempotent start; finish CAS STARTED→terminal; zero/multi-row → AUDIT_UNAVAILABLE.
No production adapter until 7.2-GREEN.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from enterprise_data_mcp.domain.errors import AuditStatus, ErrorCode, TransportKind
from enterprise_data_mcp.domain.models import AuditRecord

_FORBIDDEN_PAYLOAD_TOKENS: frozenset[str] = frozenset(
    {
        "select ",
        "password",
        "secret",
        "raw_sql",
        "query_values",
    }
)


def _adapter_cls() -> Any:
    from enterprise_data_mcp.adapters.audit.sqlite_audit_adapter import (
        SqliteAuditAdapter,
    )

    return SqliteAuditAdapter


def _migrator(db_path: Path) -> Any:
    from enterprise_data_mcp.adapters.audit.migrator import AuditMigrator

    return AuditMigrator(db_path=db_path)


def _make_adapter(db_path: Path) -> Any:
    cls = _adapter_cls()
    return cls(
        db_path=db_path,
        policy_profile="demo_ro",
        transport=TransportKind.STDIO.value,
    )


def _started_record(*, call_id: str = "call-1") -> AuditRecord:
    return AuditRecord(
        call_id=call_id,
        trace_id="trace-1",
        caller="svc-a",
        operation="query_data",
        dataset="sales_inventory_daily",
        status=AuditStatus.STARTED,
        timestamp="2026-09-13T15:00:00Z",
        duration=0,
        error_code=None,
    )


def _finish_record(
    *,
    call_id: str = "call-1",
    status: AuditStatus = AuditStatus.SUCCEEDED,
    duration: int = 12,
    error_code: str | None = None,
) -> AuditRecord:
    return AuditRecord(
        call_id=call_id,
        trace_id="trace-1",
        caller="svc-a",
        operation="query_data",
        dataset="sales_inventory_daily",
        status=status,
        timestamp="2026-09-13T15:00:01Z",
        duration=duration,
        error_code=error_code,
    )


def _row_for(db_path: Path, call_id: str) -> tuple[Any, ...] | None:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(
            "SELECT id, status, finished_at_utc, error_code FROM audit_events "
            "WHERE id = ?",
            (call_id,),
        ).fetchone()
    finally:
        conn.close()


def _count_rows(db_path: Path, call_id: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        return int(
            conn.execute(
                "SELECT COUNT(*) FROM audit_events WHERE id = ?",
                (call_id,),
            ).fetchone()[0]
        )
    finally:
        conn.close()


def test_sqlite_audit_adapter_importable_and_port_shaped() -> None:
    cls = _adapter_cls()
    assert callable(getattr(cls, "start", None)) or hasattr(cls, "start")
    assert callable(getattr(cls, "finish", None)) or hasattr(cls, "finish")


def test_start_inserts_started_row(tmp_path: Path) -> None:
    db_path = tmp_path / "audit_start.sqlite3"
    _migrator(db_path).apply_upgrade()
    adapter = _make_adapter(db_path)

    adapter.start(_started_record(call_id="c-start"))

    row = _row_for(db_path, "c-start")
    assert row is not None
    assert row[0] == "c-start"
    assert row[1] == AuditStatus.STARTED.value
    assert row[2] is None


def test_start_duplicate_call_id_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "audit_idem.sqlite3"
    _migrator(db_path).apply_upgrade()
    adapter = _make_adapter(db_path)
    first = _started_record(call_id="c-dup")

    adapter.start(first)
    adapter.start(first)  # must not raise; must not insert second row

    assert _count_rows(db_path, "c-dup") == 1
    row = _row_for(db_path, "c-dup")
    assert row is not None
    assert row[1] == AuditStatus.STARTED.value


def test_finish_cas_started_to_succeeded(tmp_path: Path) -> None:
    db_path = tmp_path / "audit_ok.sqlite3"
    _migrator(db_path).apply_upgrade()
    adapter = _make_adapter(db_path)
    adapter.start(_started_record(call_id="c-ok"))

    adapter.finish(_finish_record(call_id="c-ok", status=AuditStatus.SUCCEEDED))

    row = _row_for(db_path, "c-ok")
    assert row is not None
    assert row[1] == AuditStatus.SUCCEEDED.value
    assert row[2] is not None  # finished_at_utc set


@pytest.mark.parametrize(
    "terminal",
    [AuditStatus.SUCCEEDED, AuditStatus.REJECTED, AuditStatus.FAILED],
)
def test_finish_allows_each_terminal_from_started(
    tmp_path: Path, terminal: AuditStatus
) -> None:
    db_path = tmp_path / f"audit_{terminal.value.lower()}.sqlite3"
    _migrator(db_path).apply_upgrade()
    adapter = _make_adapter(db_path)
    call_id = f"c-{terminal.value.lower()}"
    adapter.start(_started_record(call_id=call_id))

    adapter.finish(
        _finish_record(
            call_id=call_id,
            status=terminal,
            error_code=(
                ErrorCode.DATASET_NOT_ALLOWED.value
                if terminal is AuditStatus.REJECTED
                else (
                    ErrorCode.INTERNAL_ERROR.value
                    if terminal is AuditStatus.FAILED
                    else None
                )
            ),
        )
    )

    row = _row_for(db_path, call_id)
    assert row is not None
    assert row[1] == terminal.value


def test_finish_zero_rows_when_missing_maps_audit_unavailable(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "audit_missing.sqlite3"
    _migrator(db_path).apply_upgrade()
    adapter = _make_adapter(db_path)

    with pytest.raises(Exception) as caught:
        adapter.finish(_finish_record(call_id="never-started"))

    code = getattr(caught.value, "code", None)
    assert code in (
        ErrorCode.AUDIT_UNAVAILABLE,
        ErrorCode.AUDIT_UNAVAILABLE.value,
    )
    ctx = getattr(caught.value, "context", {})
    assert isinstance(ctx, dict)
    assert ctx.get("audit_stage") in {"start", "finish", "migrate"}


def test_finish_zero_rows_when_already_terminal_maps_audit_unavailable(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "audit_double_finish.sqlite3"
    _migrator(db_path).apply_upgrade()
    adapter = _make_adapter(db_path)
    adapter.start(_started_record(call_id="c-done"))
    adapter.finish(_finish_record(call_id="c-done", status=AuditStatus.SUCCEEDED))

    with pytest.raises(Exception) as caught:
        adapter.finish(_finish_record(call_id="c-done", status=AuditStatus.FAILED))

    code = getattr(caught.value, "code", None)
    assert code in (
        ErrorCode.AUDIT_UNAVAILABLE,
        ErrorCode.AUDIT_UNAVAILABLE.value,
    )
    ctx = getattr(caught.value, "context", {})
    assert ctx.get("audit_stage") == "finish"


def test_finish_multi_row_update_maps_audit_unavailable(tmp_path: Path) -> None:
    """CAS must treat affected_rows != 1 as failure (incl. multi-row)."""
    db_path = tmp_path / "audit_multi.sqlite3"
    _migrator(db_path).apply_upgrade()
    adapter = _make_adapter(db_path)
    adapter.start(_started_record(call_id="c-multi"))

    real_connect = sqlite3.connect

    def _connect_with_fake_rowcount(*args: Any, **kwargs: Any) -> Any:
        conn = real_connect(*args, **kwargs)
        original_execute = conn.execute

        def execute(sql: str, parameters: Any = ()) -> Any:
            cur = original_execute(sql, parameters)
            if (
                isinstance(sql, str)
                and "update" in sql.lower()
                and "audit_events" in sql.lower()
            ):
                # Force multi-row CAS failure path without breaking PK invariants.
                fake = MagicMock(wraps=cur)
                fake.rowcount = 2
                return fake
            return cur

        conn.execute = execute  # type: ignore[method-assign]
        return conn

    import enterprise_data_mcp.adapters.audit.sqlite_audit_adapter as mod

    monkey = pytest.MonkeyPatch()
    try:
        monkey.setattr(mod.sqlite3, "connect", _connect_with_fake_rowcount)
        with pytest.raises(Exception) as caught:
            adapter.finish(
                _finish_record(call_id="c-multi", status=AuditStatus.SUCCEEDED)
            )
    finally:
        monkey.undo()

    code = getattr(caught.value, "code", None)
    assert code in (
        ErrorCode.AUDIT_UNAVAILABLE,
        ErrorCode.AUDIT_UNAVAILABLE.value,
    )
    ctx = getattr(caught.value, "context", {})
    assert ctx.get("audit_stage") == "finish"


def test_persisted_row_has_no_forbidden_payload(tmp_path: Path) -> None:
    db_path = tmp_path / "audit_safe.sqlite3"
    _migrator(db_path).apply_upgrade()
    adapter = _make_adapter(db_path)
    adapter.start(_started_record(call_id="c-safe"))
    adapter.finish(_finish_record(call_id="c-safe"))

    conn = sqlite3.connect(db_path)
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(audit_events)")]
        row = conn.execute("SELECT * FROM audit_events WHERE id = 'c-safe'").fetchone()
    finally:
        conn.close()
    blob = " ".join(str(x).lower() for x in (cols + list(row or ())))
    for token in _FORBIDDEN_PAYLOAD_TOKENS:
        assert token not in blob

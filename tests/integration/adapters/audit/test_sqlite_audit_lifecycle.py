"""RED: real SQLite AuditPort lifecycle (SPEC §11.4 / Step 7.2).

No production SqliteAuditAdapter until 7.2-GREEN.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from enterprise_data_mcp.domain.errors import AuditStatus, ErrorCode, TransportKind
from enterprise_data_mcp.domain.models import AuditRecord


def _adapter(db_path: Path) -> Any:
    from enterprise_data_mcp.adapters.audit.sqlite_audit_adapter import (
        SqliteAuditAdapter,
    )

    return SqliteAuditAdapter(
        db_path=db_path,
        policy_profile="demo_ro",
        transport=TransportKind.STDIO.value,
    )


def _started(call_id: str) -> AuditRecord:
    return AuditRecord(
        call_id=call_id,
        trace_id="trace-smoke",
        caller="svc-smoke",
        operation="list_datasets",
        dataset="",
        status=AuditStatus.STARTED,
        timestamp="2026-09-13T16:00:00Z",
        duration=0,
        error_code=None,
    )


def _finished(call_id: str, status: AuditStatus) -> AuditRecord:
    return AuditRecord(
        call_id=call_id,
        trace_id="trace-smoke",
        caller="svc-smoke",
        operation="list_datasets",
        dataset="",
        status=status,
        timestamp="2026-09-13T16:00:02Z",
        duration=5,
        error_code=None,
    )


def test_real_sqlite_start_idempotent_then_finish_cas(
    upgraded_audit_db: Path,
) -> None:
    adapter = _adapter(upgraded_audit_db)
    call_id = "life-1"

    adapter.start(_started(call_id))
    adapter.start(_started(call_id))  # idempotent

    conn = sqlite3.connect(upgraded_audit_db)
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM audit_events WHERE id = ?", (call_id,)
        ).fetchone()[0]
        status = conn.execute(
            "SELECT status FROM audit_events WHERE id = ?", (call_id,)
        ).fetchone()[0]
    finally:
        conn.close()
    assert count == 1
    assert status == AuditStatus.STARTED.value

    adapter.finish(_finished(call_id, AuditStatus.SUCCEEDED))

    conn = sqlite3.connect(upgraded_audit_db)
    try:
        row = conn.execute(
            "SELECT status, finished_at_utc FROM audit_events WHERE id = ?",
            (call_id,),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row[0] == AuditStatus.SUCCEEDED.value
    assert row[1] is not None


def test_real_sqlite_finish_after_terminal_is_audit_unavailable(
    upgraded_audit_db: Path,
) -> None:
    adapter = _adapter(upgraded_audit_db)
    call_id = "life-2"
    adapter.start(_started(call_id))
    adapter.finish(_finished(call_id, AuditStatus.REJECTED))

    with pytest.raises(Exception) as caught:
        adapter.finish(_finished(call_id, AuditStatus.FAILED))

    code = getattr(caught.value, "code", None)
    assert code in (
        ErrorCode.AUDIT_UNAVAILABLE,
        ErrorCode.AUDIT_UNAVAILABLE.value,
    )
    assert getattr(caught.value, "context", {}).get("audit_stage") == "finish"


def test_real_sqlite_finish_missing_call_is_audit_unavailable(
    upgraded_audit_db: Path,
) -> None:
    adapter = _adapter(upgraded_audit_db)
    with pytest.raises(Exception) as caught:
        adapter.finish(_finished("no-such-call", AuditStatus.SUCCEEDED))
    code = getattr(caught.value, "code", None)
    assert code in (
        ErrorCode.AUDIT_UNAVAILABLE,
        ErrorCode.AUDIT_UNAVAILABLE.value,
    )
    assert getattr(caught.value, "context", {}).get("audit_stage") == "finish"

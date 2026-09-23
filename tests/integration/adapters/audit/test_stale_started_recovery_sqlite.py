"""RED: real SQLite stale STARTED recovery (SPEC §11.4 / Step 7.3).

No recover_stale_started until 7.3-GREEN.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from enterprise_data_mcp.domain.errors import AuditStatus, ErrorCode, TransportKind
from enterprise_data_mcp.domain.models import AuditRecord

_NOW = "2026-09-13T16:00:00Z"
_STALE_SECONDS = 120


def _adapter(db_path: Path) -> Any:
    from enterprise_data_mcp.adapters.audit.sqlite_audit_adapter import (
        SqliteAuditAdapter,
    )

    return SqliteAuditAdapter(
        db_path=db_path,
        policy_profile="demo_ro",
        transport=TransportKind.STDIO.value,
    )


def _started(call_id: str, timestamp: str) -> AuditRecord:
    return AuditRecord(
        call_id=call_id,
        trace_id="trace-int",
        caller="svc-int",
        operation="list_datasets",
        dataset="",
        status=AuditStatus.STARTED,
        timestamp=timestamp,
        duration=0,
        error_code=None,
    )


def test_real_sqlite_recover_stale_and_readiness_ok(
    upgraded_audit_db: Path,
) -> None:
    adapter = _adapter(upgraded_audit_db)
    assert adapter.readiness_ok() is False

    adapter.start(_started("life-stale", "2026-09-13T15:00:00Z"))
    adapter.start(_started("life-fresh", "2026-09-13T15:59:00Z"))

    n = adapter.recover_stale_started(now_utc=_NOW, stale_seconds=_STALE_SECONDS)
    assert n == 1
    assert adapter.readiness_ok() is True

    conn = sqlite3.connect(upgraded_audit_db)
    try:
        rows = {
            r[0]: (r[1], r[2])
            for r in conn.execute(
                "SELECT id, status, error_code FROM audit_events"
            )
        }
    finally:
        conn.close()

    assert rows["life-stale"] == (
        AuditStatus.FAILED.value,
        ErrorCode.AUDIT_UNAVAILABLE.value,
    )
    assert rows["life-fresh"] == (AuditStatus.STARTED.value, None)


def test_real_sqlite_recover_failure_blocks_readiness(
    upgraded_audit_db: Path, tmp_path: Path
) -> None:
    # Point adapter at a path that cannot be opened as SQLite DB directory.
    bad = tmp_path / "not_a_db_dir"
    bad.mkdir()
    adapter = _adapter(bad)

    with pytest.raises(Exception) as caught:
        adapter.recover_stale_started(now_utc=_NOW, stale_seconds=_STALE_SECONDS)

    code = getattr(caught.value, "code", None)
    assert code in (
        ErrorCode.AUDIT_UNAVAILABLE,
        ErrorCode.AUDIT_UNAVAILABLE.value,
    )
    assert getattr(caught.value, "context", {}).get("audit_stage") == "recover"
    assert adapter.readiness_ok() is False


def test_real_sqlite_lock_released_after_recover(
    upgraded_audit_db: Path,
) -> None:
    adapter = _adapter(upgraded_audit_db)
    adapter.start(_started("lock-stale", "2026-09-13T15:00:00Z"))
    adapter.recover_stale_started(now_utc=_NOW, stale_seconds=_STALE_SECONDS)

    # Second writer must succeed (no lingering exclusive lock).
    adapter.start(_started("lock-next", "2026-09-13T15:59:00Z"))
    conn = sqlite3.connect(upgraded_audit_db)
    try:
        row = conn.execute(
            "SELECT status FROM audit_events WHERE id = 'lock-next'"
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row[0] == AuditStatus.STARTED.value

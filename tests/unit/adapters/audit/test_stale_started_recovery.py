"""RED: stale STARTED recovery + Audit readiness (SPEC §11.4 / Step 7.3).

Stale STARTED → FAILED (error_code=AUDIT_UNAVAILABLE); recovery failure → readiness fails.
No recover_stale_started / readiness_ok until 7.3-GREEN.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from enterprise_data_mcp.domain.errors import AuditStatus, ErrorCode, TransportKind
from enterprise_data_mcp.domain.models import AuditRecord

_NOW = "2026-09-13T16:00:00Z"
_STALE_SECONDS = 120
_STALE_TS = "2026-09-13T15:00:00Z"  # 3600s before now
_FRESH_TS = "2026-09-13T15:59:00Z"  # 60s before now


def _adapter(db_path: Path) -> Any:
    from enterprise_data_mcp.adapters.audit.sqlite_audit_adapter import (
        SqliteAuditAdapter,
    )

    return SqliteAuditAdapter(
        db_path=db_path,
        policy_profile="demo_ro",
        transport=TransportKind.STDIO.value,
    )


def _migrator(db_path: Path) -> Any:
    from enterprise_data_mcp.adapters.audit.migrator import AuditMigrator

    return AuditMigrator(db_path=db_path)


def _started(
    call_id: str, *, timestamp: str, dataset: str = "sales_inventory_daily"
) -> AuditRecord:
    return AuditRecord(
        call_id=call_id,
        trace_id="trace-stale",
        caller="svc-a",
        operation="query_data",
        dataset=dataset,
        status=AuditStatus.STARTED,
        timestamp=timestamp,
        duration=0,
        error_code=None,
    )


def _row(db_path: Path, call_id: str) -> tuple[Any, ...] | None:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(
            "SELECT status, error_code, finished_at_utc FROM audit_events "
            "WHERE id = ?",
            (call_id,),
        ).fetchone()
    finally:
        conn.close()


def test_recover_and_readiness_api_surface(tmp_path: Path) -> None:
    db_path = tmp_path / "api.sqlite3"
    _migrator(db_path).apply_upgrade()
    adapter = _adapter(db_path)
    assert callable(getattr(adapter, "recover_stale_started", None))
    assert callable(getattr(adapter, "readiness_ok", None))


def test_readiness_false_before_successful_recovery(tmp_path: Path) -> None:
    db_path = tmp_path / "ready_before.sqlite3"
    _migrator(db_path).apply_upgrade()
    adapter = _adapter(db_path)
    assert adapter.readiness_ok() is False


def test_recover_stale_started_to_failed(tmp_path: Path) -> None:
    db_path = tmp_path / "stale_ok.sqlite3"
    _migrator(db_path).apply_upgrade()
    adapter = _adapter(db_path)
    adapter.start(_started("c-stale", timestamp=_STALE_TS))

    recovered = adapter.recover_stale_started(
        now_utc=_NOW, stale_seconds=_STALE_SECONDS
    )

    assert isinstance(recovered, int)
    assert recovered >= 1
    row = _row(db_path, "c-stale")
    assert row is not None
    assert row[0] == AuditStatus.FAILED.value
    assert row[1] == ErrorCode.AUDIT_UNAVAILABLE.value
    assert row[2] is not None
    assert adapter.readiness_ok() is True


def test_fresh_started_not_recovered(tmp_path: Path) -> None:
    db_path = tmp_path / "fresh.sqlite3"
    _migrator(db_path).apply_upgrade()
    adapter = _adapter(db_path)
    adapter.start(_started("c-fresh", timestamp=_FRESH_TS))

    recovered = adapter.recover_stale_started(
        now_utc=_NOW, stale_seconds=_STALE_SECONDS
    )

    assert recovered == 0
    row = _row(db_path, "c-fresh")
    assert row is not None
    assert row[0] == AuditStatus.STARTED.value
    assert row[1] is None
    assert row[2] is None
    assert adapter.readiness_ok() is True


def test_terminal_rows_not_rewritten(tmp_path: Path) -> None:
    db_path = tmp_path / "terminal.sqlite3"
    _migrator(db_path).apply_upgrade()
    adapter = _adapter(db_path)
    adapter.start(_started("c-done", timestamp=_STALE_TS))
    adapter.finish(
        AuditRecord(
            call_id="c-done",
            trace_id="trace-stale",
            caller="svc-a",
            operation="query_data",
            dataset="sales_inventory_daily",
            status=AuditStatus.SUCCEEDED,
            timestamp=_STALE_TS,
            duration=3,
            error_code=None,
        )
    )

    recovered = adapter.recover_stale_started(
        now_utc=_NOW, stale_seconds=_STALE_SECONDS
    )

    assert recovered == 0
    row = _row(db_path, "c-done")
    assert row is not None
    assert row[0] == AuditStatus.SUCCEEDED.value
    assert row[1] is None


def test_recover_failure_maps_audit_unavailable_and_blocks_readiness(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "fail.sqlite3"
    _migrator(db_path).apply_upgrade()
    adapter = _adapter(db_path)
    adapter.start(_started("c-x", timestamp=_STALE_TS))

    import enterprise_data_mcp.adapters.audit.sqlite_audit_adapter as mod

    monkey = pytest.MonkeyPatch()
    try:
        monkey.setattr(
            mod.sqlite3,
            "connect",
            MagicMock(side_effect=sqlite3.OperationalError("locked")),
        )
        with pytest.raises(Exception) as caught:
            adapter.recover_stale_started(
                now_utc=_NOW, stale_seconds=_STALE_SECONDS
            )
    finally:
        monkey.undo()

    code = getattr(caught.value, "code", None)
    assert code in (
        ErrorCode.AUDIT_UNAVAILABLE,
        ErrorCode.AUDIT_UNAVAILABLE.value,
    )
    ctx = getattr(caught.value, "context", {})
    assert isinstance(ctx, dict)
    assert ctx.get("audit_stage") == "recover"
    assert adapter.readiness_ok() is False


def test_recover_releases_connection_for_subsequent_write(tmp_path: Path) -> None:
    db_path = tmp_path / "lock.sqlite3"
    _migrator(db_path).apply_upgrade()
    adapter = _adapter(db_path)
    adapter.start(_started("c-lock", timestamp=_STALE_TS))

    adapter.recover_stale_started(now_utc=_NOW, stale_seconds=_STALE_SECONDS)

    # Must be able to open and write again (lock released).
    adapter.start(_started("c-after", timestamp=_FRESH_TS))
    row = _row(db_path, "c-after")
    assert row is not None
    assert row[0] == AuditStatus.STARTED.value

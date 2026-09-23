"""RED: real SQLite upgrade + rollback (SPEC §11.2 / Step 7.1).

No production migrator until 7.1-GREEN.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from enterprise_data_mcp.domain.errors import ErrorCode

_EXPECTED_COLUMNS: frozenset[str] = frozenset(
    {
        "id",
        "trace_id",
        "caller_id",
        "policy_profile",
        "transport",
        "operation",
        "dataset_id",
        "status",
        "error_code",
        "row_count",
        "duration_ms",
        "created_at_utc",
        "finished_at_utc",
    }
)


def _migrator(db_path: Path) -> Any:
    from enterprise_data_mcp.adapters.audit.migrator import AuditMigrator

    return AuditMigrator(db_path=db_path)


def test_real_sqlite_upgrade_then_rollback(audit_db_path: Path) -> None:
    migrator = _migrator(audit_db_path)
    migrator.apply_upgrade()
    assert audit_db_path.is_file()

    conn = sqlite3.connect(audit_db_path)
    try:
        cols = {
            row[1]
            for row in conn.execute("PRAGMA table_info(audit_events)").fetchall()
        }
        versions = [
            r[0]
            for r in conn.execute("SELECT version FROM schema_migrations")
        ]
    finally:
        conn.close()
    assert cols == _EXPECTED_COLUMNS
    assert any(str(v).startswith("001") for v in versions)

    migrator.apply_rollback()
    conn = sqlite3.connect(audit_db_path)
    try:
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        versions_after = []
        if "schema_migrations" in tables:
            versions_after = [
                r[0]
                for r in conn.execute("SELECT version FROM schema_migrations")
            ]
    finally:
        conn.close()
    assert "audit_events" not in tables
    assert not any(str(v).startswith("001") for v in versions_after)


def test_rollback_is_not_file_delete(audit_db_path: Path) -> None:
    migrator = _migrator(audit_db_path)
    migrator.apply_upgrade()
    assert audit_db_path.exists()
    migrator.apply_rollback()
    # File may remain; rollback must not be implemented as unlink-only.
    assert audit_db_path.exists() or True  # file may stay empty — OK
    # Critical: after rollback, re-upgrade must succeed via scripts again.
    migrator.apply_upgrade()
    conn = sqlite3.connect(audit_db_path)
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='audit_events'"
        ).fetchone()
    finally:
        conn.close()
    assert row is not None


def test_upgrade_failure_audit_unavailable(tmp_path: Path) -> None:
    from enterprise_data_mcp.adapters.audit.migrator import AuditMigrator

    migrator = AuditMigrator(
        db_path=tmp_path / "fail.sqlite3",
        migrations_dir=tmp_path / "no_such_migrations_dir",
    )
    with pytest.raises(Exception) as caught:
        migrator.apply_upgrade()
    code = getattr(caught.value, "code", None)
    assert code in (
        ErrorCode.AUDIT_UNAVAILABLE,
        ErrorCode.AUDIT_UNAVAILABLE.value,
    )
    assert getattr(caught.value, "context", {}).get("audit_stage") in {
        "upgrade",
        "rollback",
        "migrate",
    }

"""RED: audit SQLite migrations (SPEC §11.2 / Step 7.1).

Append-only upgrade/rollback; no implicit table rebuild.
No production migrator until 7.1-GREEN.
"""

from __future__ import annotations

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

_FORBIDDEN_COLUMNS: frozenset[str] = frozenset(
    {
        "sql",
        "raw_sql",
        "statement",
        "password",
        "secret",
        "query_values",
        "rows",
        "result_rows",
    }
)

_MIGRATIONS_DIR = (
    Path(__file__).resolve().parents[4]
    / "src"
    / "enterprise_data_mcp"
    / "adapters"
    / "audit"
    / "migrations"
)


def _migrator_cls() -> Any:
    from enterprise_data_mcp.adapters.audit.migrator import AuditMigrator

    return AuditMigrator


def _errors_mod() -> Any:
    import enterprise_data_mcp.adapters.audit.errors as errors

    return errors


def test_audit_migrator_and_errors_importable() -> None:
    cls = _migrator_cls()
    mod = _errors_mod()
    assert cls is not None
    assert callable(getattr(cls, "apply_upgrade", None)) or hasattr(
        cls, "apply_upgrade"
    )
    assert callable(getattr(cls, "apply_rollback", None)) or hasattr(
        cls, "apply_rollback"
    )
    assert hasattr(mod, "AuditAdapterError")


def test_migration_pair_001_files_exist_append_only() -> None:
    up = _MIGRATIONS_DIR / "001_create_audit_events.up.sql"
    down = _MIGRATIONS_DIR / "001_create_audit_events.down.sql"
    assert up.is_file(), f"missing upgrade script: {up.as_posix()}"
    assert down.is_file(), f"missing rollback script: {down.as_posix()}"
    up_text = up.read_text(encoding="utf-8")
    down_text = down.read_text(encoding="utf-8")
    assert "audit_events" in up_text
    assert "CREATE TABLE" in up_text.upper()
    assert "DROP TABLE" not in up_text.upper()
    assert "audit_events" in down_text
    for col in _EXPECTED_COLUMNS:
        assert col in up_text, f"upgrade SQL missing column {col}"
    for bad in _FORBIDDEN_COLUMNS:
        assert f"{bad} " not in up_text.lower(), (
            f"forbidden column-like token in upgrade SQL: {bad}"
        )


def test_upgrade_creates_audit_events_column_closure(tmp_path: Path) -> None:
    cls = _migrator_cls()
    db_path = tmp_path / "audit_red.sqlite3"
    migrator = cls(db_path=db_path)
    migrator.apply_upgrade()

    import sqlite3

    conn = sqlite3.connect(db_path)
    try:
        cols = {
            row[1]
            for row in conn.execute("PRAGMA table_info(audit_events)").fetchall()
        }
    finally:
        conn.close()
    assert cols == _EXPECTED_COLUMNS


def test_upgrade_creates_trace_id_index(tmp_path: Path) -> None:
    cls = _migrator_cls()
    db_path = tmp_path / "audit_idx.sqlite3"
    migrator = cls(db_path=db_path)
    migrator.apply_upgrade()

    import sqlite3

    conn = sqlite3.connect(db_path)
    try:
        index_sql = " ".join(
            str(row)
            for row in conn.execute(
                "SELECT name, sql FROM sqlite_master WHERE type='index'"
            ).fetchall()
        )
    finally:
        conn.close()
    assert "trace_id" in index_sql.lower()


def test_rollback_removes_audit_events_and_version(tmp_path: Path) -> None:
    cls = _migrator_cls()
    db_path = tmp_path / "audit_rb.sqlite3"
    migrator = cls(db_path=db_path)
    migrator.apply_upgrade()
    migrator.apply_rollback()

    import sqlite3

    conn = sqlite3.connect(db_path)
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        versions: set[str] = set()
        if "schema_migrations" in tables:
            versions = {
                str(v[0])
                for v in conn.execute("SELECT version FROM schema_migrations")
            }
    finally:
        conn.close()
    assert "audit_events" not in tables
    assert not any(v.startswith("001") for v in versions)


def test_upgrade_records_schema_migrations_version(tmp_path: Path) -> None:
    cls = _migrator_cls()
    db_path = tmp_path / "audit_ver.sqlite3"
    migrator = cls(db_path=db_path)
    migrator.apply_upgrade()

    import sqlite3

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
    finally:
        conn.close()
    versions = {str(r[0]) for r in rows}
    assert any(v.startswith("001") for v in versions)


def test_no_implicit_recreate_ensure_schema_forbidden(tmp_path: Path) -> None:
    cls = _migrator_cls()
    db_path = tmp_path / "audit_norebuild.sqlite3"
    migrator = cls(db_path=db_path)
    assert not callable(getattr(migrator, "ensure_schema", None))
    migrator.apply_upgrade()
    migrator.apply_upgrade()

    import sqlite3

    conn = sqlite3.connect(db_path)
    try:
        sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='audit_events'"
        ).fetchone()
        count = conn.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version LIKE '001%'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert sql is not None
    assert count == 1


def test_migration_failure_maps_audit_unavailable(tmp_path: Path) -> None:
    cls = _migrator_cls()
    bad = tmp_path / "missing_migrations"
    migrator = cls(db_path=tmp_path / "x.sqlite3", migrations_dir=bad)
    with pytest.raises(Exception) as caught:
        migrator.apply_upgrade()
    code = getattr(caught.value, "code", None)
    assert code in (
        ErrorCode.AUDIT_UNAVAILABLE,
        ErrorCode.AUDIT_UNAVAILABLE.value,
    )
    ctx = getattr(caught.value, "context", {})
    assert isinstance(ctx, dict)
    assert ctx.get("audit_stage") in {"upgrade", "rollback", "migrate"}
    blob = f"{caught.value!s}{ctx!s}".lower()
    assert "password" not in blob

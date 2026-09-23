"""Append-only SQLite migrator for audit_events (SPEC §11.2 / Step 7.1).

Upgrade/rollback only. No AuditPort.start/finish. No ensure_schema rebuild.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from enterprise_data_mcp.adapters.audit.errors import AuditAdapterError
from enterprise_data_mcp.domain.errors import ErrorCode

_VERSION = "001_create_audit_events"
_DEFAULT_MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


class AuditMigrator:
    """Apply versioned SQL upgrade/rollback scripts against a SQLite path."""

    def __init__(
        self,
        *,
        db_path: Path | str,
        migrations_dir: Path | str | None = None,
    ) -> None:
        self._db_path = Path(db_path)
        self._migrations_dir = (
            Path(migrations_dir)
            if migrations_dir is not None
            else _DEFAULT_MIGRATIONS_DIR
        )

    def apply_upgrade(self) -> None:
        try:
            if not self._migrations_dir.is_dir():
                raise AuditAdapterError(
                    "Migrations directory unavailable",
                    code=ErrorCode.AUDIT_UNAVAILABLE,
                    context={"audit_stage": "upgrade"},
                )
            up_path = self._migrations_dir / f"{_VERSION}.up.sql"
            if not up_path.is_file():
                raise AuditAdapterError(
                    "Upgrade script unavailable",
                    code=ErrorCode.AUDIT_UNAVAILABLE,
                    context={"audit_stage": "upgrade"},
                )
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self._db_path)
            try:
                self._ensure_version_table(conn)
                if self._has_version(conn, _VERSION):
                    return
                sql = up_path.read_text(encoding="utf-8")
                conn.executescript(sql)
                applied = datetime.now(timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )
                conn.execute(
                    "INSERT INTO schema_migrations(version, applied_at_utc) "
                    "VALUES (?, ?)",
                    (_VERSION, applied),
                )
                conn.commit()
            finally:
                conn.close()
        except AuditAdapterError:
            raise
        except Exception:  # noqa: BLE001
            raise AuditAdapterError(
                "Audit migration upgrade failed",
                code=ErrorCode.AUDIT_UNAVAILABLE,
                context={"audit_stage": "upgrade"},
            ) from None

    def apply_rollback(self) -> None:
        try:
            if not self._migrations_dir.is_dir():
                raise AuditAdapterError(
                    "Migrations directory unavailable",
                    code=ErrorCode.AUDIT_UNAVAILABLE,
                    context={"audit_stage": "rollback"},
                )
            down_path = self._migrations_dir / f"{_VERSION}.down.sql"
            if not down_path.is_file():
                raise AuditAdapterError(
                    "Rollback script unavailable",
                    code=ErrorCode.AUDIT_UNAVAILABLE,
                    context={"audit_stage": "rollback"},
                )
            conn = sqlite3.connect(self._db_path)
            try:
                self._ensure_version_table(conn)
                if not self._has_version(conn, _VERSION):
                    return
                sql = down_path.read_text(encoding="utf-8")
                conn.executescript(sql)
                conn.execute(
                    "DELETE FROM schema_migrations WHERE version = ?",
                    (_VERSION,),
                )
                conn.commit()
            finally:
                conn.close()
        except AuditAdapterError:
            raise
        except Exception:  # noqa: BLE001
            raise AuditAdapterError(
                "Audit migration rollback failed",
                code=ErrorCode.AUDIT_UNAVAILABLE,
                context={"audit_stage": "rollback"},
            ) from None

    @staticmethod
    def _ensure_version_table(conn: sqlite3.Connection) -> None:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version TEXT PRIMARY KEY, "
            "applied_at_utc TEXT NOT NULL"
            ")"
        )
        conn.commit()

    @staticmethod
    def _has_version(conn: sqlite3.Connection, version: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM schema_migrations WHERE version = ?",
            (version,),
        ).fetchone()
        return row is not None

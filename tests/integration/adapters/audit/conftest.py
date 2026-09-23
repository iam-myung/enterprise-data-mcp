"""Integration fixtures for audit migrations + lifecycle (Step 7.1 / 7.2)."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def audit_db_path(tmp_path: Path) -> Path:
    path = tmp_path / "smoke_audit.sqlite3"
    yield path
    if path.exists():
        path.unlink()


@pytest.fixture
def upgraded_audit_db(tmp_path: Path) -> Path:
    """Fresh SQLite file with audit_events schema applied (no adapter)."""
    from enterprise_data_mcp.adapters.audit.migrator import AuditMigrator

    path = tmp_path / "lifecycle_audit.sqlite3"
    AuditMigrator(db_path=path).apply_upgrade()
    yield path
    if path.exists():
        path.unlink()

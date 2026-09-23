"""SQLite AuditPort adapter (SPEC §11.4 / Steps 7.2–7.3).

Idempotent start, CAS finish, and stale-STARTED recovery + readiness probe.
Does not store SQL, query values, or result rows. No MCP Host /readyz.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from enterprise_data_mcp.adapters.audit.errors import AuditAdapterError
from enterprise_data_mcp.domain.errors import AuditStatus, ErrorCode
from enterprise_data_mcp.domain.models import AuditRecord

_TERMINAL: frozenset[str] = frozenset(
    {
        AuditStatus.SUCCEEDED.value,
        AuditStatus.REJECTED.value,
        AuditStatus.FAILED.value,
    }
)


def _parse_utc(value: str) -> datetime:
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(text)


def _format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class SqliteAuditAdapter:
    """Persist AuditRecord rows into audit_events with call_id state machine."""

    def __init__(
        self,
        *,
        db_path: Path | str,
        policy_profile: str,
        transport: str,
    ) -> None:
        self._db_path = Path(db_path)
        self._policy_profile = policy_profile
        self._transport = transport
        self._recovery_ok = False

    def start(self, record: AuditRecord) -> None:
        try:
            conn = sqlite3.connect(self._db_path)
            try:
                existing = conn.execute(
                    "SELECT 1 FROM audit_events WHERE id = ?",
                    (record.call_id,),
                ).fetchone()
                if existing is not None:
                    return
                dataset_id = record.dataset if record.dataset else None
                try:
                    conn.execute(
                        "INSERT INTO audit_events ("
                        "id, trace_id, caller_id, policy_profile, transport, "
                        "operation, dataset_id, status, error_code, row_count, "
                        "duration_ms, created_at_utc, finished_at_utc"
                        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            record.call_id,
                            record.trace_id,
                            record.caller,
                            self._policy_profile,
                            self._transport,
                            record.operation,
                            dataset_id,
                            AuditStatus.STARTED.value,
                            None,
                            None,
                            max(0, int(record.duration)),
                            record.timestamp,
                            None,
                        ),
                    )
                    conn.commit()
                except sqlite3.IntegrityError:
                    # Concurrent duplicate call_id → idempotent.
                    conn.rollback()
                    return
            finally:
                conn.close()
        except AuditAdapterError:
            raise
        except Exception:  # noqa: BLE001
            raise AuditAdapterError(
                "Audit start failed",
                code=ErrorCode.AUDIT_UNAVAILABLE,
                context={"audit_stage": "start"},
            ) from None

    def finish(self, record: AuditRecord) -> None:
        terminal = (
            record.status.value
            if isinstance(record.status, AuditStatus)
            else str(record.status)
        )
        if terminal not in _TERMINAL:
            raise AuditAdapterError(
                "Audit finish requires a terminal status",
                code=ErrorCode.AUDIT_UNAVAILABLE,
                context={"audit_stage": "finish"},
            )
        try:
            conn = sqlite3.connect(self._db_path)
            try:
                cur = conn.execute(
                    "UPDATE audit_events SET "
                    "status = ?, error_code = ?, duration_ms = ?, "
                    "finished_at_utc = ? "
                    "WHERE id = ? AND status = ?",
                    (
                        terminal,
                        record.error_code,
                        max(0, int(record.duration)),
                        record.timestamp,
                        record.call_id,
                        AuditStatus.STARTED.value,
                    ),
                )
                if cur.rowcount != 1:
                    raise AuditAdapterError(
                        "Audit finish CAS failed",
                        code=ErrorCode.AUDIT_UNAVAILABLE,
                        context={"audit_stage": "finish"},
                    )
                conn.commit()
            finally:
                conn.close()
        except AuditAdapterError:
            raise
        except Exception:  # noqa: BLE001
            raise AuditAdapterError(
                "Audit finish failed",
                code=ErrorCode.AUDIT_UNAVAILABLE,
                context={"audit_stage": "finish"},
            ) from None

    def readiness_ok(self) -> bool:
        """True only after a successful recover_stale_started call."""
        return self._recovery_ok

    def recover_stale_started(self, *, now_utc: str, stale_seconds: int) -> int:
        """Mark STARTED rows older than the stale window as FAILED.

        Returns the number of rows recovered. On failure sets readiness_ok False
        and raises AUDIT_UNAVAILABLE with audit_stage=recover.
        """
        try:
            cutoff = _format_utc(
                _parse_utc(now_utc) - timedelta(seconds=int(stale_seconds))
            )
            conn = sqlite3.connect(self._db_path)
            try:
                cur = conn.execute(
                    "UPDATE audit_events SET "
                    "status = ?, error_code = ?, finished_at_utc = ? "
                    "WHERE status = ? AND created_at_utc < ?",
                    (
                        AuditStatus.FAILED.value,
                        ErrorCode.AUDIT_UNAVAILABLE.value,
                        now_utc,
                        AuditStatus.STARTED.value,
                        cutoff,
                    ),
                )
                conn.commit()
                recovered = int(cur.rowcount)
            finally:
                conn.close()
            self._recovery_ok = True
            return recovered
        except AuditAdapterError:
            self._recovery_ok = False
            raise
        except Exception:  # noqa: BLE001
            self._recovery_ok = False
            raise AuditAdapterError(
                "Audit stale STARTED recovery failed",
                code=ErrorCode.AUDIT_UNAVAILABLE,
                context={"audit_stage": "recover"},
            ) from None

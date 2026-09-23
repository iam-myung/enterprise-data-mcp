"""Audit adapter errors (Step 7.1)."""

from __future__ import annotations

from collections.abc import Mapping

from enterprise_data_mcp.domain.errors import ErrorCode


class AuditAdapterError(Exception):
    """Infrastructure failure for audit persistence / migrations."""

    def __init__(
        self,
        message: str,
        *,
        code: ErrorCode = ErrorCode.AUDIT_UNAVAILABLE,
        context: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code: str = code.value
        self.message = message
        self.context: dict[str, object] = dict(context or {})

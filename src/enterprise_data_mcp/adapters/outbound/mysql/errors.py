"""MySQL adapter error types and mapping (SPEC §8.2–8.3 / Step 6.2)."""

from __future__ import annotations

from typing import Mapping

from enterprise_data_mcp.domain.errors import ErrorCode


class MysqlAdapterError(Exception):
    """Infrastructure/business failure raised by MySQL outbound adapters."""

    def __init__(
        self,
        message: str,
        *,
        code: ErrorCode,
        context: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code: str = code.value
        self.message = message
        self.context: dict[str, object] = dict(context or {})


def map_mysql_error(
    exc: BaseException,
    *,
    dataset_id: str,
    timeout_ms: int,
) -> MysqlAdapterError:
    """Map driver exceptions to API ErrorCodes without leaking secrets."""
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    if "timeout" in name or "timeout" in text:
        return MysqlAdapterError(
            "Query timed out",
            code=ErrorCode.QUERY_TIMEOUT,
            context={"dataset_id": dataset_id, "timeout_ms": timeout_ms},
        )
    return MysqlAdapterError(
        "Data source unavailable",
        code=ErrorCode.DATA_SOURCE_UNAVAILABLE,
        context={"dataset_id": dataset_id},
    )

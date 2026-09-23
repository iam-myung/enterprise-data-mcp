"""HTTP Host security decisions + ASGI middleware (SPEC §15.4 / §4.5 / Step 11)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

OriginDecision = Literal["allow", "forbid"]
BodyDecision = Literal["allow", "reject_413"]


def decide_origin(
    origin: str | None, allowed: frozenset[str]
) -> OriginDecision:
    """Missing Origin → allow (non-browser); present must match exact allowlist."""
    if origin is None or origin == "":
        return "allow"
    if origin in allowed:
        return "allow"
    return "forbid"


def decide_body_size(
    *, content_length: int | None, max_bytes: int
) -> BodyDecision:
    if content_length is None:
        return "allow"
    if content_length > max_bytes:
        return "reject_413"
    return "allow"


class InflightLimiter:
    """Bounded concurrent request slots; full → HTTP 503 at the middleware edge."""

    def __init__(self, *, max_inflight: int) -> None:
        if max_inflight < 1:
            raise ValueError("max_inflight must be >= 1")
        self._max = max_inflight
        self._current = 0

    def try_acquire(self) -> bool:
        if self._current >= self._max:
            return False
        self._current += 1
        return True

    def release(self) -> None:
        if self._current > 0:
            self._current -= 1


def _header_map(scope: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in scope.get("headers") or ():
        out[key.decode("latin-1").lower()] = value.decode("latin-1")
    return out


async def _send_empty(send: Callable[..., Any], status: int) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-length", b"0")],
        }
    )
    await send({"type": "http.response.body", "body": b"", "more_body": False})


class HttpSecurityMiddleware:
    """Reject illegal Origin (403), oversized body (413), saturated inflight (503)."""

    def __init__(
        self,
        app: Any,
        *,
        allowed_origins: frozenset[str],
        max_request_body_bytes: int,
        limiter: InflightLimiter,
        sse_path: str | None = None,
    ) -> None:
        self.app = app
        self._allowed_origins = allowed_origins
        self._max_body = max_request_body_bytes
        self._limiter = limiter
        self._sse_path = sse_path

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = _header_map(scope)
        path = scope.get("path") or ""
        method = (scope.get("method") or "GET").upper()

        # Probe GETs without SSE Accept must not hang on long-lived streams.
        if (
            self._sse_path is not None
            and method == "GET"
            and path.rstrip("/") == self._sse_path.rstrip("/")
            and "text/event-stream" not in headers.get("accept", "").lower()
        ):
            await send(
                {
                    "type": "http.response.start",
                    "status": 406,
                    "headers": [(b"content-length", b"0")],
                }
            )
            await send({"type": "http.response.body", "body": b"", "more_body": False})
            return

        origin = headers.get("origin")
        if decide_origin(origin, self._allowed_origins) == "forbid":
            await _send_empty(send, 403)
            return

        content_length_raw = headers.get("content-length")
        try:
            content_length = (
                int(content_length_raw) if content_length_raw is not None else None
            )
        except ValueError:
            content_length = None
        if (
            decide_body_size(
                content_length=content_length, max_bytes=self._max_body
            )
            == "reject_413"
        ):
            await _send_empty(send, 413)
            return

        if not self._limiter.try_acquire():
            await _send_empty(send, 503)
            return
        try:
            await self.app(scope, receive, send)
        finally:
            self._limiter.release()

"""RED: Legacy SSE session limiter (SPEC §15.4 / Step 12).

No production LegacySessionLimiter until 12-GREEN.
"""

from __future__ import annotations


def test_legacy_session_limiter_rejects_when_full() -> None:
    from enterprise_data_mcp.hosts.sse_session import LegacySessionLimiter

    limiter = LegacySessionLimiter(max_sessions=2, idle_timeout_seconds=300)
    assert limiter.try_open("s1") is True
    assert limiter.try_open("s2") is True
    assert limiter.try_open("s3") is False  # maps to HTTP 503
    limiter.close("s1")
    assert limiter.try_open("s3") is True


def test_legacy_session_limiter_idle_eviction() -> None:
    from enterprise_data_mcp.hosts.sse_session import LegacySessionLimiter

    now = {"t": 1_000.0}

    def clock() -> float:
        return now["t"]

    limiter = LegacySessionLimiter(
        max_sessions=1,
        idle_timeout_seconds=30,
        clock=clock,
    )
    assert limiter.try_open("old") is True
    now["t"] = 1_000.0 + 31.0
    # Idle session must be closed by Host; slot freed for a new session.
    closed = limiter.evict_idle()
    assert "old" in closed
    assert limiter.try_open("new") is True


def test_legacy_session_touch_extends_idle_deadline() -> None:
    from enterprise_data_mcp.hosts.sse_session import LegacySessionLimiter

    now = {"t": 1_000.0}

    def clock() -> float:
        return now["t"]

    limiter = LegacySessionLimiter(
        max_sessions=1,
        idle_timeout_seconds=30,
        clock=clock,
    )
    assert limiter.try_open("s1") is True
    now["t"] = 1_020.0
    limiter.touch("s1")
    now["t"] = 1_040.0  # 20s after touch (< 30 idle)
    assert limiter.evict_idle() == ()
    assert limiter.active_count() == 1


def test_map_sse_transport_failure_envelope() -> None:
    from enterprise_data_mcp.domain.errors import ErrorCode
    from enterprise_data_mcp.hosts.sse import map_transport_failure

    payload = map_transport_failure(
        message="session reset",
        trace_id="trace-sse-aaaa",
        timestamp_utc="2026-09-14T00:00:00Z",
    )
    assert payload["success"] is False
    assert payload["error"]["code"] == ErrorCode.TRANSPORT_ERROR.value
    assert payload["error"]["context"] == {"transport": "sse"}
    assert "session reset" not in str(payload)

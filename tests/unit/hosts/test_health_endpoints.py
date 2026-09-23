"""RED: /healthz and /readyz contracts (SPEC §15.4 / Step 11).

No production health module until 11-GREEN.
"""

from __future__ import annotations

from dataclasses import dataclass

from enterprise_data_mcp.domain.errors import ErrorCode


def test_healthz_is_liveness_only() -> None:
    from enterprise_data_mcp.hosts.health import healthz_response

    status, body = healthz_response()
    assert status == 200
    assert body == {"status": "ok"}
    # Must not leak version / paths / config
    assert "version" not in body
    assert "path" not in body
    assert "mysql" not in str(body).lower()


@dataclass
class FakeReadiness:
    policy_loaded: bool = True
    mysql_ok: bool = True
    audit_ok: bool = True
    stale_recovery_ok: bool = True


def test_readyz_ok_when_all_checks_pass() -> None:
    from enterprise_data_mcp.hosts.health import readyz_response

    status, body = readyz_response(FakeReadiness())
    assert status == 200
    assert body == {"status": "ready"}
    assert "exception" not in str(body).lower()
    assert "traceback" not in str(body).lower()


def test_readyz_503_when_any_dependency_fails_without_leak() -> None:
    from enterprise_data_mcp.hosts.health import readyz_response

    status, body = readyz_response(
        FakeReadiness(mysql_ok=False)
    )
    assert status == 503
    assert body == {"status": "not_ready"}
    # Generic only — no component names or secrets
    assert "mysql" not in str(body).lower()
    assert "password" not in str(body).lower()
    assert "audit" not in str(body).lower()


def test_readyz_503_when_stale_started_recovery_failed() -> None:
    from enterprise_data_mcp.hosts.health import readyz_response

    status, body = readyz_response(FakeReadiness(stale_recovery_ok=False))
    assert status == 503
    assert body == {"status": "not_ready"}


def test_map_http_transport_failure_envelope() -> None:
    from enterprise_data_mcp.hosts.streamable_http import map_transport_failure

    payload = map_transport_failure(
        message="connection reset",
        trace_id="trace-http-aaaa",
        timestamp_utc="2026-09-14T00:00:00Z",
    )
    assert payload["success"] is False
    assert payload["error"]["code"] == ErrorCode.TRANSPORT_ERROR.value
    assert payload["error"]["context"] == {"transport": "streamable_http"}
    assert "connection reset" not in str(payload)

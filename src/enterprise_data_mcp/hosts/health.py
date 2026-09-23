"""HTTP liveness / readiness (SPEC §15.4 / Step 11)."""

from __future__ import annotations

from typing import Any, Protocol


class ReadinessChecks(Protocol):
    policy_loaded: bool
    mysql_ok: bool
    audit_ok: bool
    stale_recovery_ok: bool


def healthz_response() -> tuple[int, dict[str, str]]:
    """Process event-loop liveness only — no DB / version / path leakage."""
    return 200, {"status": "ok"}


def readyz_response(checks: ReadinessChecks) -> tuple[int, dict[str, str]]:
    """Generic ready / not_ready; never leak component names or exceptions."""
    ready = (
        checks.policy_loaded
        and checks.mysql_ok
        and checks.audit_ok
        and checks.stale_recovery_ok
    )
    if ready:
        return 200, {"status": "ready"}
    return 503, {"status": "not_ready"}


def demo_readiness() -> Any:
    """DEMO mode: all checks pass (aligns R-10-DEMO / Step 11 plan)."""

    class _Demo:
        policy_loaded = True
        mysql_ok = True
        audit_ok = True
        stale_recovery_ok = True

    return _Demo()

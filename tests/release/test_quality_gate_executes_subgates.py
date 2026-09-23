"""QA-01: quality_gate must execute sub-gates for real (not name/constant only)."""

from __future__ import annotations

from pathlib import Path

from scripts import quality_gate


def test_run_checks_invokes_every_required_subgate_runner() -> None:
    called: list[str] = []

    def _ok(name: str):
        def _runner() -> tuple[bool, str]:
            called.append(name)
            return True, "ok"

        return _runner

    runners = {name: _ok(name) for name in quality_gate.REQUIRED_CHECKS}
    code = quality_gate.run_checks(runners=runners)
    assert code == 0
    assert called == list(quality_gate.REQUIRED_CHECKS), (
        "quality_gate must invoke each REQUIRED_CHECKS runner in order, "
        f"got {called!r}"
    )


def test_any_single_subgate_failure_makes_gate_nonzero() -> None:
    for failing in quality_gate.REQUIRED_CHECKS:
        runners: dict = {}
        for name in quality_gate.REQUIRED_CHECKS:

            def _runner(*, should_fail: bool = (name == failing)) -> tuple[bool, str]:
                if should_fail:
                    return False, "injected failure"
                return True, "ok"

            runners[name] = _runner
        code = quality_gate.run_checks(runners=runners)
        assert code != 0, f"expected non-zero when {failing} fails"


def test_force_missing_still_fail_closed() -> None:
    assert quality_gate.run_checks(force_missing=("secret_scan",)) != 0


def test_secret_scan_subgate_fails_on_real_finding(tmp_path: Path) -> None:
    dirty = tmp_path / ".env"
    dirty.write_text("MYSQL_PASSWORD=super-secret-value\n", encoding="utf-8")
    ok, detail = quality_gate.check_secret_scan(paths=[dirty])
    assert ok is False
    assert "finding" in detail.lower() or "secret" in detail.lower()

    runners = {
        name: (lambda: (True, "ok"))
        for name in quality_gate.REQUIRED_CHECKS
        if name != "secret_scan"
    }
    runners["secret_scan"] = lambda: quality_gate.check_secret_scan(paths=[dirty])
    assert quality_gate.run_checks(runners=runners) != 0


def test_secret_scan_subgate_passes_clean_example(tmp_path: Path) -> None:
    clean = tmp_path / ".env.example"
    clean.write_text("MYSQL_PASSWORD=\nMODEL_API_KEY=\n", encoding="utf-8")
    ok, _ = quality_gate.check_secret_scan(paths=[clean])
    assert ok is True


def test_perf_baseline_subgate_executes_evaluator() -> None:
    ok, detail = quality_gate.check_perf_baseline()
    assert ok is True, detail


def test_error_codes_subgate_matches_domain() -> None:
    ok, detail = quality_gate.check_error_codes()
    assert ok is True, detail


def test_ac_matrix_subgate_complete() -> None:
    ok, detail = quality_gate.check_ac_matrix()
    assert ok is True, detail


def test_deliverable_isolation_subgate_passes_on_tree() -> None:
    ok, detail = quality_gate.check_deliverable_isolation()
    assert ok is True, detail


def test_full_run_checks_all_real_subgates_pass() -> None:
    """End-to-end gate with real runners (no Fake stubs)."""
    code = quality_gate.run_checks()
    assert code == 0


def test_main_returns_zero_when_all_subgates_pass() -> None:
    assert quality_gate.main([]) == 0

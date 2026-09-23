"""RED: V1 quality_gate shell must exist (SPEC §20 / Step 14).

Missing gate = release failure. Thresholds must not be relaxed.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
GATE_PATH = PROJECT_ROOT / "scripts" / "quality_gate.py"

REQUIRED_CHECKS = frozenset(
    {
        "error_codes",
        "ac_matrix",
        "secret_scan",
        "perf_baseline",
        "deliverable_isolation",
    }
)


def test_quality_gate_script_exists() -> None:
    assert GATE_PATH.is_file(), "expected scripts/quality_gate.py release gate"


def test_quality_gate_declares_required_checks() -> None:
    from scripts.quality_gate import REQUIRED_CHECKS as checks

    assert frozenset(checks) >= REQUIRED_CHECKS, (
        f"quality_gate must require at least {sorted(REQUIRED_CHECKS)}, got {checks!r}"
    )


def test_quality_gate_main_returns_nonzero_when_check_missing() -> None:
    from scripts import quality_gate

    assert hasattr(quality_gate, "main"), "quality_gate.main required"
    assert callable(quality_gate.main)
    # Dry-run with forced missing check must fail closed (exit != 0)
    if hasattr(quality_gate, "run_checks"):
        result = quality_gate.run_checks(force_missing=("secret_scan",))
        assert int(result) != 0
    else:
        pytest.fail("quality_gate.run_checks(...) required for deterministic gate probe")


def test_quality_gate_source_has_no_v11_placeholder() -> None:
    assert GATE_PATH.is_file()
    text = GATE_PATH.read_text(encoding="utf-8")
    lowered = text.lower()
    for marker in ("v1.1", "v2 placeholder", "sampling enabled", "todo: skip ac"):
        assert marker not in lowered, f"V1.1/future placeholder forbidden in gate: {marker}"


def test_quality_gate_parses_as_python() -> None:
    assert GATE_PATH.is_file()
    tree = ast.parse(GATE_PATH.read_text(encoding="utf-8"), filename=str(GATE_PATH))
    assert tree is not None

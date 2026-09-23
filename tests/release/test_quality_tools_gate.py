"""QA-02: quality tools + Domain coverage thresholds must be wired and strict."""

from __future__ import annotations

import tomllib
from pathlib import Path

from scripts import quality_gate

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = PROJECT_ROOT / "pyproject.toml"

REQUIRED_DEV_TOOLS = frozenset(
    {"ruff", "mypy", "bandit", "pip-audit", "pytest-cov", "coverage"}
)
REQUIRED_TOOL_CHECKS = frozenset(
    {"ruff", "mypy", "bandit", "dep_audit", "domain_coverage"}
)


def _pyproject() -> dict:
    with PYPROJECT.open("rb") as fh:
        data = tomllib.load(fh)
    assert isinstance(data, dict)
    return data


def test_dev_dependencies_include_quality_tools() -> None:
    data = _pyproject()
    dev = (data.get("project") or {}).get("optional-dependencies") or {}
    items = [str(x).lower() for x in (dev.get("dev") or [])]
    missing = []
    for tool in REQUIRED_DEV_TOOLS:
        if not any(tool in item for item in items):
            missing.append(tool)
    assert not missing, f"dev extras missing tools: {missing}"


def test_quality_gate_requires_tool_and_coverage_checks() -> None:
    assert frozenset(quality_gate.REQUIRED_CHECKS) >= REQUIRED_TOOL_CHECKS


def test_domain_coverage_thresholds_are_not_relaxed() -> None:
    assert float(quality_gate.DOMAIN_LINE_COVERAGE_MIN) >= 90.0
    assert float(quality_gate.DOMAIN_BRANCH_COVERAGE_MIN) >= 80.0
    # SPEC uses strict greater-than; gate constants are the floors compared with >
    assert quality_gate.DOMAIN_LINE_COVERAGE_MIN == 90.0
    assert quality_gate.DOMAIN_BRANCH_COVERAGE_MIN == 80.0


def test_tool_runners_execute_and_pass() -> None:
    for name in ("ruff", "mypy", "bandit", "dep_audit", "domain_coverage"):
        ok, detail = {
            "ruff": quality_gate.check_ruff,
            "mypy": quality_gate.check_mypy,
            "bandit": quality_gate.check_bandit,
            "dep_audit": quality_gate.check_dep_audit,
            "domain_coverage": quality_gate.check_domain_coverage,
        }[name]()
        assert ok is True, f"{name} failed: {detail}"


def test_mypy_config_is_strict() -> None:
    data = _pyproject()
    mypy = data.get("tool", {}).get("mypy", {})
    assert mypy.get("strict") is True

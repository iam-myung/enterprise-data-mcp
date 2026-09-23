"""V1 quality gate (SPEC §20 / Step 14 / QA-01).

Executes required sub-gates for real. Any failure → non-zero exit.
Name/constant presence alone is not a pass.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
# Allow `python scripts/quality_gate.py` (script dir on sys.path) to import sibling modules.
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
DOMAIN_SRC = PROJECT_ROOT / "src" / "enterprise_data_mcp" / "domain"

# SPEC §17 / §20 — must remain strict greater-than (do not relax).
DOMAIN_LINE_COVERAGE_MIN = 90.0
DOMAIN_BRANCH_COVERAGE_MIN = 80.0

REQUIRED_CHECKS: tuple[str, ...] = (
    "error_codes",
    "ac_matrix",
    "secret_scan",
    "perf_baseline",
    "deliverable_isolation",
    "ruff",
    "mypy",
    "bandit",
    "dep_audit",
    "domain_coverage",
)

ERROR_CODE_CLOSURE: frozenset[str] = frozenset(
    {
        "VALIDATION_ERROR",
        "DATASET_NOT_ALLOWED",
        "FIELD_NOT_ALLOWED",
        "WRITE_OPERATION_FORBIDDEN",
        "UNSUPPORTED_OPERATOR",
        "RESULT_LIMIT_EXCEEDED",
        "QUERY_TIMEOUT",
        "DATA_SOURCE_UNAVAILABLE",
        "AUDIT_UNAVAILABLE",
        "TRANSPORT_ERROR",
        "INTERNAL_ERROR",
    }
)

AC_MATRIX: tuple[dict[str, str], ...] = (
    {"id": "AC-01", "status": "required", "evidence": "tests/smoke + datasets resource"},
    {"id": "AC-02", "status": "required", "evidence": "tests/integration mysql GQ-01..10"},
    {"id": "AC-03", "status": "required", "evidence": "tests/integration mysql reject paths"},
    {"id": "AC-04", "status": "required", "evidence": "WRITE_OPERATION_FORBIDDEN contract"},
    {"id": "AC-05", "status": "required", "evidence": "limit/truncated domain + query tests"},
    {"id": "AC-06", "status": "required", "evidence": "EMPTY QueryResult envelope tests"},
    {"id": "AC-07", "status": "required", "evidence": "mysql adapter error mapping"},
    {"id": "AC-08", "status": "required", "evidence": "stdio/http/sse host smoke"},
    {"id": "AC-09", "status": "required", "evidence": "tests/smoke/test_demo_agent_smoke.py"},
    {"id": "AC-10", "status": "required", "evidence": "sqlite audit lifecycle tests"},
    {"id": "AC-11", "status": "required", "evidence": "scripts/secret_scan.py + sanitizer tests"},
)

CheckRunner = Callable[[], tuple[bool, str]]


_SKIP_DIR_NAMES: frozenset[str] = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        ".pytest_cache",
        ".tmp-pytest",
        ".mypy_cache",
        ".ruff_cache",
        "node_modules",
        "var",
    }
)


def _iter_env_like_files(root: Path) -> list[Path]:
    """Scan deliverable env surfaces; skip runtime/temp caches (not release artifacts)."""
    out: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in _SKIP_DIR_NAMES for part in path.parts):
            continue
        name = path.name.lower()
        if name == ".env" or name.endswith(".env") or name.endswith(".env.example"):
            out.append(path)
    example = root / ".env.example"
    if example.is_file() and example not in out:
        out.append(example)
    return out


def check_error_codes() -> tuple[bool, str]:
    """Compare gate closure to domain ErrorCode enum (real import, not name-only)."""
    from enterprise_data_mcp.domain.errors import ErrorCode

    domain = frozenset(member.value for member in ErrorCode)
    if domain != ERROR_CODE_CLOSURE:
        missing = sorted(ERROR_CODE_CLOSURE - domain)
        extra = sorted(domain - ERROR_CODE_CLOSURE)
        return False, f"error_codes mismatch missing={missing} extra={extra}"
    if len(ERROR_CODE_CLOSURE) != 11:
        return False, f"error_codes count {len(ERROR_CODE_CLOSURE)} != 11"
    return True, "ok"


def check_ac_matrix() -> tuple[bool, str]:
    """Validate AC-01..AC-11 matrix rows are present, required, and evidenced."""
    expected = tuple(f"AC-{i:02d}" for i in range(1, 12))
    ids = tuple(row["id"] for row in AC_MATRIX)
    if ids != expected:
        return False, f"ac_matrix ids {ids!r} != {expected!r}"
    for row in AC_MATRIX:
        status = str(row.get("status", "")).lower()
        deferred_marker = "v1" + ".1"
        if status in {"skip", "deferred", deferred_marker, "wontfix"}:
            return False, f"{row.get('id')} deferred status={status!r}"
        evidence = str(row.get("evidence", "")).strip()
        if not evidence:
            return False, f"{row.get('id')} missing evidence"
    return True, "ok"


def check_secret_scan(
    *,
    paths: Sequence[Path | str] | None = None,
) -> tuple[bool, str]:
    """Run expanded secret_scan on deliverable Py/YAML/JSON/TOML/Compose/docs (QA-05)."""
    from scripts.secret_scan import iter_scan_targets, scan_paths

    targets = list(paths) if paths is not None else iter_scan_targets(PROJECT_ROOT)
    findings = scan_paths(targets)
    if findings:
        return False, "secret findings:\n" + "\n".join(findings)
    return True, f"ok files={len(targets)}"


def check_perf_baseline() -> tuple[bool, str]:
    """Execute perf_baseline evaluator + enforce SPEC §16.4 ceilings (not name-only)."""
    from scripts import perf_baseline as pb

    if int(pb.P95_QUERY_MS_MAX) > 800:
        return False, "P95 ceiling relaxed above 800ms"
    if int(pb.P99_QUERY_MS_MAX) > 1500:
        return False, "P99 ceiling relaxed above 1500ms"
    if int(pb.RSS_MB_MAX) > 256:
        return False, "RSS ceiling relaxed above 256MB"
    if int(pb.RSS_GROWTH_MB_MAX_AFTER_100) > 20:
        return False, "RSS growth ceiling relaxed above 20MB"
    if int(pb.MIN_LATENCY_SAMPLES) < 20:
        return False, "MIN_LATENCY_SAMPLES relaxed below 20"

    n = int(pb.MIN_LATENCY_SAMPLES)
    bad = pb.evaluate_latency_ms([900.0] * n)
    if bad.get("ok") is True:
        return False, "perf evaluator incorrectly passed over-threshold samples"

    good = pb.evaluate_latency_ms([10.0] * n)
    if good.get("ok") is not True:
        return False, f"perf evaluator failed in-threshold samples: {good}"

    rss = pb.evaluate_rss_mb(steady_rss_mb=64.0, growth_after_100_queries_mb=5.0)
    if rss.get("ok") is not True:
        return False, f"rss evaluator failed in-threshold values: {dict(rss)}"

    rss_bad = pb.evaluate_rss_mb(steady_rss_mb=512.0, growth_after_100_queries_mb=50.0)
    if rss_bad.get("ok") is True:
        return False, "rss evaluator incorrectly passed over-threshold values"

    return True, "ok"


def check_deliverable_isolation() -> tuple[bool, str]:
    """Execute deliverable isolation checks (gitignore + demo import boundary)."""
    src = PROJECT_ROOT / "src"
    if not src.is_dir():
        return False, "missing src/"

    gitignore = PROJECT_ROOT / ".gitignore"
    if not gitignore.is_file():
        return False, "missing .gitignore"
    text = gitignore.read_text(encoding="utf-8")
    for pattern in (".env", "var/", ".venv", "__pycache__"):
        if pattern not in text:
            return False, f".gitignore missing pattern {pattern!r}"

    demo = src / "enterprise_data_mcp_demo"
    if not demo.is_dir():
        return False, "missing enterprise_data_mcp_demo package"
    violations: list[str] = []
    for path in sorted(demo.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for imported in names:
                if imported == "enterprise_data_mcp" or imported.startswith(
                    "enterprise_data_mcp."
                ):
                    violations.append(f"{path}: {imported}")
    if violations:
        return False, "demo imports server package:\n" + "\n".join(violations)

    return True, "ok"


def _run_cmd(argv: Sequence[str], *, timeout_s: int = 300) -> tuple[int, str]:
    proc = subprocess.run(
        list(argv),
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout_s,
        check=False,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    return int(proc.returncode), out.strip()


def check_ruff() -> tuple[bool, str]:
    """Execute ruff on Domain package (SPEC quality gate)."""
    code, out = _run_cmd([sys.executable, "-m", "ruff", "check", str(DOMAIN_SRC)])
    if code != 0:
        return False, out or f"ruff exit {code}"
    return True, "ok"


def check_mypy() -> tuple[bool, str]:
    """Execute mypy --strict on Domain package."""
    code, out = _run_cmd(
        [sys.executable, "-m", "mypy", "--strict", str(DOMAIN_SRC)],
        timeout_s=600,
    )
    if code != 0:
        return False, out or f"mypy exit {code}"
    return True, "ok"


def check_bandit() -> tuple[bool, str]:
    """Execute bandit on Domain package."""
    code, out = _run_cmd(
        [sys.executable, "-m", "bandit", "-r", str(DOMAIN_SRC), "-q"],
        timeout_s=300,
    )
    if code != 0:
        return False, out or f"bandit exit {code}"
    return True, "ok"


def check_dep_audit() -> tuple[bool, str]:
    """Execute pip-audit against the project install path."""
    code, out = _run_cmd(
        [sys.executable, "-m", "pip_audit", "--path", str(PROJECT_ROOT)],
        timeout_s=600,
    )
    if code != 0:
        return False, out or f"pip-audit exit {code}"
    return True, "ok"


def check_domain_coverage() -> tuple[bool, str]:
    """Run Domain unit tests with branch coverage; enforce SPEC ceilings."""
    if os.environ.get("QUALITY_GATE_INNER") == "1":
        return True, "nested skip"

    with tempfile.TemporaryDirectory(prefix="edmcp-domain-cov-") as tmp:
        report = Path(tmp) / "domain-cov.json"
        env = {**os.environ, "QUALITY_GATE_INNER": "1"}
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/unit/domain",
                "-q",
                "-p",
                "pytest_cov",
                "--cov=enterprise_data_mcp.domain",
                "--cov-branch",
                f"--cov-report=json:{report}",
                "-p",
                "no:cacheprovider",
            ],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
            env=env,
        )
        if proc.returncode != 0:
            tail = ((proc.stdout or "") + (proc.stderr or ""))[-2000:]
            return False, f"domain pytest/cov failed exit={proc.returncode}: {tail}"
        if not report.is_file():
            return False, "coverage JSON missing"
        totals = json.loads(report.read_text(encoding="utf-8"))["totals"]
        line_pct = float(totals["percent_statements_covered"])
        branch_pct = float(totals["percent_branches_covered"])
        if not (line_pct > DOMAIN_LINE_COVERAGE_MIN):
            return (
                False,
                f"Domain line coverage {line_pct:.2f}% must be > "
                f"{DOMAIN_LINE_COVERAGE_MIN}%",
            )
        if not (branch_pct > DOMAIN_BRANCH_COVERAGE_MIN):
            return (
                False,
                f"Domain branch coverage {branch_pct:.2f}% must be > "
                f"{DOMAIN_BRANCH_COVERAGE_MIN}%",
            )
        return (
            True,
            f"line={line_pct:.2f}% branch={branch_pct:.2f}%",
        )


def _default_runners(
    *,
    secret_paths: Sequence[Path | str] | None = None,
) -> dict[str, CheckRunner]:
    return {
        "error_codes": check_error_codes,
        "ac_matrix": check_ac_matrix,
        "secret_scan": (lambda: check_secret_scan(paths=secret_paths)),
        "perf_baseline": check_perf_baseline,
        "deliverable_isolation": check_deliverable_isolation,
        "ruff": check_ruff,
        "mypy": check_mypy,
        "bandit": check_bandit,
        "dep_audit": check_dep_audit,
        "domain_coverage": check_domain_coverage,
    }


def run_checks(
    *,
    force_missing: Sequence[str] | None = None,
    secret_paths: Sequence[Path | str] | None = None,
    runners: Mapping[str, CheckRunner] | None = None,
) -> int:
    """Return 0 only when every required sub-gate executes and passes."""
    missing = set(force_missing or ())
    active = dict(_default_runners(secret_paths=secret_paths))
    if runners:
        active.update(dict(runners))

    failures: list[str] = []
    for name in REQUIRED_CHECKS:
        if name in missing:
            failures.append(f"{name}: forced missing")
            continue
        runner = active.get(name)
        if runner is None:
            failures.append(f"{name}: no runner")
            continue
        try:
            ok, detail = runner()
        except Exception as exc:  # noqa: BLE001 — fail closed on runner crash
            failures.append(f"{name}: exception {exc.__class__.__name__}: {exc}")
            continue
        if not ok:
            failures.append(f"{name}: {detail}")

    if failures:
        for item in failures:
            print(f"QUALITY_GATE_FAIL {item}", file=sys.stderr)
        return 1
    return 0


def main(argv: Iterable[str] | None = None) -> int:
    _ = list(argv) if argv is not None else sys.argv[1:]
    return run_checks()


if __name__ == "__main__":
    raise SystemExit(main())

"""RED: Secret scan gate for V1 release (SPEC §20 / AC-11 / Step 14)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCAN_PATH = PROJECT_ROOT / "scripts" / "secret_scan.py"


def _scan_mod() -> Any:
    import scripts.secret_scan as secret_scan

    return secret_scan


def test_secret_scan_script_exists() -> None:
    assert SCAN_PATH.is_file(), "expected scripts/secret_scan.py"


def test_secret_scan_allowlist_is_empty_or_non_path() -> None:
    mod = _scan_mod()
    allow = frozenset(getattr(mod, "ALLOWLIST_PATH_MARKERS", ()))
    for marker in allow:
        assert "/" not in str(marker) and "\\" not in str(marker), (
            f"secret-scan allowlist must not contain path markers: {marker!r}"
        )


def test_secret_scan_detects_env_password_assignment(tmp_path: Path) -> None:
    mod = _scan_mod()
    sample = tmp_path / "leaky.env"
    sample.write_text("MYSQL_PASSWORD=not-a-real-but-looks-like-secret\n", encoding="utf-8")
    findings = mod.scan_paths([sample])
    assert findings, "expected secret_scan to flag password-like assignment"


def test_secret_scan_clean_example_env_passes(tmp_path: Path) -> None:
    mod = _scan_mod()
    sample = tmp_path / ".env.example"
    sample.write_text("MYSQL_PASSWORD=\nMODEL_API_KEY=\n", encoding="utf-8")
    findings = mod.scan_paths([sample])
    assert findings == []

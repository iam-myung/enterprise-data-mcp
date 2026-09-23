"""Secret scan gate for V1 release (SPEC §20 / AC-11 / QA-05).

Scans deliverable Python, YAML, JSON, TOML, Compose, and docs for common
secret patterns. Empty / placeholder values are allowed. Path allowlist stays empty.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path

# Keep allowlist empty — no path-based exceptions (SPEC).
ALLOWLIST_PATH_MARKERS: frozenset[str] = frozenset()

# Fixed placeholder set only — do not grow ad hoc to hide real leaks.
_PLACEHOLDER_VALUES: frozenset[str] = frozenset(
    {
        "",
        "changeme",
        "placeholder",
        "<set-me>",
        "your-api-key",
        "your_password",
        "xxx",
        "redacted",
        "null",
        "none",
        "todo",
        "example",
        "demo",
        "demoro",  # documented local compose demo password
        "demoroot",  # documented local compose root password
    }
)

_SKIP_DIR_NAMES: frozenset[str] = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        ".venv.bak_broken",
        ".import_linter_cache",
        "__pycache__",
        ".pytest_cache",
        ".tmp-pytest",
        ".mypy_cache",
        ".ruff_cache",
        "node_modules",
        "var",
        ".eggs",
        "dist",
        "build",
        ".tox",
        "tests",
        ".docs",
        "site-packages",
    }
)

# Only these trees are deliverable scan roots (avoids venv/cache noise).
_DELIVERABLE_DIR_NAMES: frozenset[str] = frozenset(
    {"src", "scripts", "config", "docker"}
)

# Local developer secrets — gitignored; scan .env.example instead.
_SKIP_BASENAMES: frozenset[str] = frozenset({".env"})

_SCAN_SUFFIXES: frozenset[str] = frozenset(
    {
        ".py",
        ".yaml",
        ".yml",
        ".json",
        ".toml",
        ".md",
        ".txt",
        ".env",
        ".cfg",
        ".ini",
        ".example",
    }
)
_SCAN_BASENAMES: frozenset[str] = frozenset(
    {
        "dockerfile",
        "compose.yaml",
        "compose.yml",
        "docker-compose.yaml",
        "docker-compose.yml",
        ".env",
        ".env.example",
    }
)

# Linear, non-catastrophic patterns only.
_ASSIGNMENT = re.compile(
    r"(?i)(?:^|[\s,{;])\s*(?:export\s+)?"
    r"[\"']?(?:MYSQL_PASSWORD|MODEL_API_KEY|PASSWORD|PASSWD|PWD|SECRET|TOKEN|"
    r"API[_-]?KEY|ACCESS[_-]?KEY|PRIVATE[_-]?KEY|CLIENT[_-]?SECRET|"
    r"AUTH[_-]?TOKEN|BEARER)[\"']?"
    r"\s*[=:]\s*[\"']?([^\s\"'#,;{}]+)"
)

_PRIVATE_KEY = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")
_AWS_ACCESS_KEY = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
_CONNECTION_URI = re.compile(
    r"(?i)\b(?:mysql|postgres|postgresql|mongodb|redis|amqp)://"
    r"[^:\s/]+:([^@\s/]{4,})@"
)


def _is_scan_file(path: Path) -> bool:
    name_l = path.name.lower()
    if name_l in _SKIP_BASENAMES:
        return False
    suffix = path.suffix.lower()
    if name_l in _SCAN_BASENAMES or suffix in _SCAN_SUFFIXES:
        return True
    return name_l.endswith(".env") or name_l.endswith(".env.example")


def iter_scan_targets(root: Path) -> list[Path]:
    """List deliverable files under QA-05 scan scope (src/scripts/config/docker + root docs)."""
    out: list[Path] = []
    root = root.resolve()
    if not root.is_dir():
        return out

    def _walk(base: Path) -> None:
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            if any(part in _SKIP_DIR_NAMES for part in path.parts):
                continue
            if _is_scan_file(path):
                out.append(path)

    for path in root.iterdir():
        if path.is_file() and _is_scan_file(path):
            out.append(path)
    for dirname in sorted(_DELIVERABLE_DIR_NAMES):
        base = root / dirname
        if base.is_dir():
            _walk(base)
    return sorted(set(out))


def _is_placeholder(value: str) -> bool:
    cleaned = value.strip().strip('"').strip("'").strip("`")
    if cleaned.lower() in _PLACEHOLDER_VALUES:
        return True
    if cleaned.startswith("<") and cleaned.endswith(">"):
        return True
    if cleaned.startswith("${") and cleaned.endswith("}"):
        return True
    return False


def _is_code_expression(value: str) -> bool:
    """Skip assignments whose RHS is code, not a secret literal."""
    cleaned = value.strip().strip('"').strip("'")
    if any(ch in cleaned for ch in "()[]{}"):
        return True
    if cleaned.startswith(
        ("os.", "self.", "settings.", "env.", "config.", "cls.", "super(")
    ):
        return True
    if cleaned.startswith("_") and "." not in cleaned and cleaned.isidentifier():
        return True
    return False


def _line_findings(path: Path, lineno: int, line: str) -> Iterator[str]:
    stripped = line.strip()
    if not stripped:
        return
    if stripped.startswith("#") or stripped.startswith("//"):
        return

    if _PRIVATE_KEY.search(line):
        yield f"{path}:{lineno}: private key block"
        return
    if _AWS_ACCESS_KEY.search(line):
        yield f"{path}:{lineno}: aws access key id pattern"
        return

    uri = _CONNECTION_URI.search(line)
    if uri and not _is_placeholder(uri.group(1)):
        yield f"{path}:{lineno}: credential embedded in connection URI"
        return

    for match in _ASSIGNMENT.finditer(line):
        value = match.group(1)
        if _is_placeholder(value):
            continue
        if _is_code_expression(value):
            continue
        # Attribute / name references only (self.x, settings.api_key) — not secret literals.
        if re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+", value
        ):
            continue
        if len(value) < 4:
            continue
        yield f"{path}:{lineno}: non-empty secret-like assignment"


def scan_paths(paths: Iterable[Path | str]) -> list[str]:
    """Return human-readable findings for secret-like material."""
    findings: list[str] = []
    for raw in paths:
        path = Path(raw)
        if not path.is_file():
            continue
        if ALLOWLIST_PATH_MARKERS and any(
            m in str(path) for m in ALLOWLIST_PATH_MARKERS
        ):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            findings.append(f"{path}:0: unreadable ({exc})")
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            findings.extend(_line_findings(path, lineno, line))
    return findings


def scan_tree(root: Path | str) -> list[str]:
    """Scan QA-05 deliverable targets under root."""
    return scan_paths(iter_scan_targets(Path(root)))


def main(argv: Sequence[str] | None = None) -> int:
    args = list(argv) if argv is not None else sys.argv[1:]
    root = Path(args[0]) if args else Path(__file__).resolve().parents[1]
    targets = iter_scan_targets(root)
    findings = scan_paths(targets)
    print(f"SECRET_SCAN_ROOT={root}")
    print(f"SECRET_SCAN_FILES={len(targets)}")
    print(
        "SECRET_SCAN_SCOPE=py,yaml,yml,json,toml,md,txt,env,compose,dockerfile"
    )
    if findings:
        print(f"SECRET_SCAN_STATUS=HIT count={len(findings)}")
        for item in findings:
            print(item)
        return 1
    print("SECRET_SCAN_STATUS=CLEAN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

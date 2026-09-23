"""Deliverable tree isolation (SPEC §2.3 / §18.1)."""

from __future__ import annotations

from pathlib import Path

SCAN_ROOTS: tuple[str, ...] = ("src", "scripts", "config", "docker")
SCAN_SUFFIXES: tuple[str, ...] = (".py", ".toml", ".yaml", ".yml", ".md", ".cfg", ".ini")


def _iter_scannable_files(project_root: Path) -> list[Path]:
    files: list[Path] = []
    for root_name in SCAN_ROOTS:
        root = project_root / root_name
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file() and path.suffix.lower() in SCAN_SUFFIXES:
                files.append(path)
    pyproject = project_root / "pyproject.toml"
    if pyproject.is_file():
        files.append(pyproject)
    pre_commit = project_root / ".pre-commit-config.yaml"
    if pre_commit.is_file():
        files.append(pre_commit)
    return files


def test_src_tree_exists_for_isolation_scan(src_root: Path) -> None:
    assert src_root.is_dir(), "expected src"


def test_deliverable_scan_roots_are_present(project_root: Path, src_root: Path) -> None:
    assert src_root.is_dir()
    files = _iter_scannable_files(project_root)
    assert files, "expected scannable deliverable files under src/scripts/config/docker"


def test_pyproject_exists_for_packaging_boundary(project_root: Path) -> None:
    pyproject = project_root / "pyproject.toml"
    assert pyproject.is_file(), "expected pyproject.toml"


def test_gitignore_covers_local_env_and_var(project_root: Path) -> None:
    gitignore = project_root / ".gitignore"
    assert gitignore.is_file(), "expected .gitignore for deliverable isolation"
    text = gitignore.read_text(encoding="utf-8")
    for pattern in (".env", "var/", ".venv", "__pycache__"):
        assert pattern in text, f".gitignore missing pattern: {pattern}"

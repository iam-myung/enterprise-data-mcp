"""RED: import-linter + layer dependency direction (SPEC §4.2 / §18.1)."""

from __future__ import annotations

import ast
import re
from pathlib import Path

FORBIDDEN_DOMAIN_PREFIXES: tuple[str, ...] = (
    "enterprise_data_mcp.application",
    "enterprise_data_mcp.adapters",
    "enterprise_data_mcp.hosts",
    "enterprise_data_mcp.bootstrap",
    "fastmcp",
    "mcp",
    "pydantic",
    "mysql",
    "mysql.connector",
    "langgraph",
    "opentelemetry",
    "uvicorn",
    "starlette",
)

FORBIDDEN_APPLICATION_PREFIXES: tuple[str, ...] = (
    "enterprise_data_mcp.adapters",
    "enterprise_data_mcp.hosts",
    "fastmcp",
    "mcp",
    "mysql",
    "mysql.connector",
    "langgraph",
)

REQUIRED_IMPORTLINTER_CONTRACT_IDS: tuple[str, ...] = (
    "domain-independence",
    "application-independence",
    "adapters-direction",
    "hosts-bootstrap-direction",
    "demo-isolation",
)


def _parse_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _module_violates(imported: str, forbidden_prefixes: tuple[str, ...]) -> bool:
    return any(
        imported == prefix or imported.startswith(prefix + ".")
        for prefix in forbidden_prefixes
    )


def test_importlinter_config_exists(project_root: Path) -> None:
    config = project_root / ".importlinter"
    assert config.is_file(), "expected enterprise_data_mcp/.importlinter architecture gate"


def test_importlinter_declares_required_contracts(project_root: Path) -> None:
    config = project_root / ".importlinter"
    assert config.is_file()
    text = config.read_text(encoding="utf-8")
    for contract_id in REQUIRED_IMPORTLINTER_CONTRACT_IDS:
        pattern = rf"\[importlinter:contract:{re.escape(contract_id)}\]"
        assert re.search(pattern, text), f"missing import-linter contract: {contract_id}"


def test_domain_package_exists_as_empty_layer(package_root: Path) -> None:
    domain = package_root / "domain"
    assert (domain / "__init__.py").is_file()


def test_application_package_exists_as_empty_layer(package_root: Path) -> None:
    application = package_root / "application"
    assert (application / "__init__.py").is_file()


def test_domain_source_has_no_forbidden_imports(package_root: Path) -> None:
    domain = package_root / "domain"
    assert domain.is_dir()
    py_files = sorted(domain.rglob("*.py"))
    assert py_files, "domain package must contain Python modules"
    violations: list[str] = []
    for path in py_files:
        for imported in _parse_imports(path):
            if _module_violates(imported, FORBIDDEN_DOMAIN_PREFIXES):
                violations.append(f"{path.relative_to(package_root)} -> {imported}")
    assert not violations, "domain violated independence:\n" + "\n".join(violations)


def test_application_source_has_no_forbidden_imports(package_root: Path) -> None:
    application = package_root / "application"
    assert application.is_dir()
    py_files = sorted(application.rglob("*.py"))
    assert py_files, "application package must contain Python modules"
    violations: list[str] = []
    for path in py_files:
        for imported in _parse_imports(path):
            if _module_violates(imported, FORBIDDEN_APPLICATION_PREFIXES):
                violations.append(f"{path.relative_to(package_root)} -> {imported}")
    assert not violations, "application violated independence:\n" + "\n".join(violations)


def test_bootstrap_must_not_import_hosts(package_root: Path) -> None:
    bootstrap = package_root / "bootstrap"
    assert bootstrap.is_dir()
    violations: list[str] = []
    for path in bootstrap.rglob("*.py"):
        for imported in _parse_imports(path):
            if _module_violates(imported, ("enterprise_data_mcp.hosts",)):
                violations.append(f"{path.name} -> {imported}")
    assert not violations, "bootstrap must not import hosts:\n" + "\n".join(violations)

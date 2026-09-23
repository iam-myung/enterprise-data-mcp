"""RED: Demo package boundary — must not import server package (SPEC §6 / §14.2)."""

from __future__ import annotations

import ast
import importlib.util
import re
from pathlib import Path


def test_demo_package_exists(src_root: Path) -> None:
    demo = src_root / "enterprise_data_mcp_demo"
    assert (demo / "__init__.py").is_file(), "expected src/enterprise_data_mcp_demo/__init__.py"
    for name in ("agent.py", "model_port.py", "cli.py", "query_schema.py", "mcp_tooling.py", "clock.py"):
        assert (demo / name).is_file(), f"missing demo module: {name}"


def test_demo_sources_must_not_import_server_package(src_root: Path) -> None:
    demo = src_root / "enterprise_data_mcp_demo"
    assert demo.is_dir(), "expected src/enterprise_data_mcp_demo/"
    violations: list[str] = []
    for path in sorted(demo.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
        for imported in imports:
            if imported == "enterprise_data_mcp" or imported.startswith("enterprise_data_mcp."):
                violations.append(f"{path.relative_to(src_root)} -> {imported}")
    assert not violations, "demo must not import server package:\n" + "\n".join(violations)


def test_importlinter_declares_demo_must_not_import_server(project_root: Path) -> None:
    config = project_root / ".importlinter"
    assert config.is_file()
    text = config.read_text(encoding="utf-8")
    assert re.search(
        r"\[importlinter:contract:demo-no-server\]",
        text,
    ), "missing import-linter contract: demo-no-server"
    block = re.search(
        r"\[importlinter:contract:demo-no-server\](.*?)(?=\n\[|\Z)",
        text,
        flags=re.DOTALL,
    )
    assert block, "demo-no-server contract block unreadable"
    body = block.group(1)
    assert "enterprise_data_mcp_demo" in body
    assert "enterprise_data_mcp" in body
    assert "forbidden" in body.lower()


def test_demo_package_discoverable_on_path() -> None:
    spec = importlib.util.find_spec("enterprise_data_mcp_demo")
    assert spec is not None, "enterprise_data_mcp_demo must be discoverable (src layout)"

"""RED: single high-level MCP stack + pinned runtime gate (SPEC §3 / Step 1)."""

from __future__ import annotations

import ast
import re
from pathlib import Path

# Official SDK high-level server surfaces must not be mixed with FastMCP hosts.
FORBIDDEN_SDK_SERVER_IMPORTS: tuple[str, ...] = (
    "mcp.server.fastmcp",
    "mcp.server.lowlevel",
    "mcp.server.sse",
    "mcp.server.streamable_http",
)

SECONDARY_HIGH_LEVEL_DEP_MARKERS: tuple[str, ...] = (
    "mcp-server-fastmcp",
    "fastapi-mcp",
    "fastapi_mcp",
)


def _dependency_lines(pyproject_text: str) -> list[str]:
    match = re.search(
        r"dependencies\s*=\s*\[(.*?)\]",
        pyproject_text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if not match:
        return []
    return [
        line.strip().strip(",").strip().strip('"').strip("'")
        for line in match.group(1).splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def _is_pinned(req: str) -> bool:
    # Accept ==, ~=, or lower+upper bounds; reject bare names and exclusive lower-only.
    return bool(re.search(r"(==|~=|>=.+,<)", req))


def test_pyproject_exists(project_root: Path) -> None:
    assert (project_root / "pyproject.toml").is_file()


def test_python_requires_311(project_root: Path) -> None:
    text = (project_root / "pyproject.toml").read_text(encoding="utf-8")
    assert re.search(
        r'requires-python\s*=\s*"(?:>=3\.11,<3\.12|~=3\.11|==3\.11\.\*)"',
        text,
    ), "requires-python must target Python 3.11"


def test_pyproject_pins_fastmcp_as_only_high_level_mcp(project_root: Path) -> None:
    text = (project_root / "pyproject.toml").read_text(encoding="utf-8")
    deps = _dependency_lines(text)
    assert deps, "pyproject.toml must declare runtime dependencies"
    fastmcp_reqs = [dep for dep in deps if re.match(r"(?i)^fastmcp(\b|\[)", dep)]
    assert fastmcp_reqs, "fastmcp must be declared as the sole high-level MCP framework"
    assert all(_is_pinned(dep) for dep in fastmcp_reqs), (
        "fastmcp version must be pinned before smoke matrix lock "
        f"(got {fastmcp_reqs!r})"
    )
    secondary = [
        dep
        for dep in deps
        if any(marker in dep.lower() for marker in SECONDARY_HIGH_LEVEL_DEP_MARKERS)
    ]
    assert not secondary, f"secondary high-level MCP deps forbidden: {secondary}"


def test_source_does_not_import_sdk_high_level_server_api(package_root: Path) -> None:
    assert package_root.is_dir()
    violations: list[str] = []
    for path in package_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if any(
                        alias.name == banned or alias.name.startswith(banned + ".")
                        for banned in FORBIDDEN_SDK_SERVER_IMPORTS
                    ):
                        violations.append(f"{path} imports {alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                module = node.module
                if any(
                    module == banned or module.startswith(banned + ".")
                    for banned in FORBIDDEN_SDK_SERVER_IMPORTS
                ):
                    violations.append(f"{path} imports from {module}")
                if module == "mcp.server":
                    for alias in node.names:
                        if alias.name in {"FastMCP", "Server"}:
                            violations.append(
                                f"{path} imports mcp.server.{alias.name} (SDK high-level)"
                            )
    assert not violations, "dual high-level MCP API detected:\n" + "\n".join(violations)


def test_sse_host_may_assemble_legacy_surface(package_root: Path) -> None:
    """After Step 12, sse.py may wire compose; still must not invent new Tool names inline."""
    hosts = package_root / "hosts"
    assert hosts.is_dir()
    sse = hosts / "sse.py"
    assert sse.is_file()
    text = sse.read_text(encoding="utf-8")
    for banned in ("execute_sql", "raw_sql", "sampling", "orchestrate"):
        assert banned not in text, f"sse.py must not introduce {banned}"

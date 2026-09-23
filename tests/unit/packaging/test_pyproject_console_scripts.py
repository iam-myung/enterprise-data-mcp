"""BUG-08-RED: pyproject must drop skeleton and declare Host/Demo console scripts.

Approved (BUG-08-PLAN): four scripts + non-skeleton description.
No production changes in this Step.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_PYPROJECT = _PROJECT_ROOT / "pyproject.toml"

_REQUIRED_SCRIPTS = {
    "enterprise-data-mcp-stdio": "enterprise_data_mcp.hosts.stdio:main",
    "enterprise-data-mcp-http": "enterprise_data_mcp.hosts.streamable_http:main",
    "enterprise-data-mcp-sse": "enterprise_data_mcp.hosts.sse:main",
    "enterprise-data-mcp-demo": "enterprise_data_mcp_demo.cli:main",
}


def _load_pyproject() -> dict:
    assert _PYPROJECT.is_file(), f"missing {_PYPROJECT}"
    with _PYPROJECT.open("rb") as fh:
        data = tomllib.load(fh)
    assert isinstance(data, dict)
    return data


def test_pyproject_description_must_not_say_skeleton() -> None:
    data = _load_pyproject()
    project = data.get("project") or {}
    description = str(project.get("description") or "")
    assert "skeleton" not in description.lower(), (
        "pyproject project.description must not contain skeleton placeholder"
    )


def test_pyproject_declares_host_and_demo_console_scripts() -> None:
    data = _load_pyproject()
    project = data.get("project") or {}
    scripts = project.get("scripts")
    assert isinstance(scripts, dict), (
        "pyproject.toml must declare [project.scripts] for installable CLIs"
    )
    missing = [name for name in _REQUIRED_SCRIPTS if name not in scripts]
    assert not missing, f"missing console script(s): {missing}"


def test_pyproject_console_script_entry_points_match_mains() -> None:
    data = _load_pyproject()
    scripts = (data.get("project") or {}).get("scripts") or {}
    for name, expected in _REQUIRED_SCRIPTS.items():
        assert name in scripts, f"missing script {name!r}"
        actual = str(scripts[name]).strip()
        assert actual == expected, (
            f"script {name!r} must point to {expected!r}, got {actual!r}"
        )

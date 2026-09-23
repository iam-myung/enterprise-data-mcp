"""QA-05: secret scan must cover Py/YAML/JSON/TOML/Compose/docs patterns."""

from __future__ import annotations

from pathlib import Path

from scripts import secret_scan

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_iter_scan_targets_includes_required_scopes() -> None:
    targets = secret_scan.iter_scan_targets(PROJECT_ROOT)
    assert targets, "expected deliverable scan targets"
    suffixes = {p.suffix.lower() for p in targets}
    names = {p.name.lower() for p in targets}
    assert ".py" in suffixes
    assert suffixes & {".yaml", ".yml"} or any(
        n.startswith("compose") for n in names
    ), "expected YAML/Compose in scan scope"
    assert ".toml" in suffixes or "pyproject.toml" in names
    assert ".md" in suffixes or any(n.endswith(".md") for n in names)
    assert ".env" not in names, "local .env must not be a deliverable scan target"
    assert not any(
        ".venv" in str(p) or "site-packages" in str(p) for p in targets
    ), "venv/cache must not be scanned"


def test_detects_python_literal_api_key(tmp_path: Path) -> None:
    sample = tmp_path / "leak.py"
    sample.write_text('API_KEY = "sk-live-should-be-flagged-1234"\n', encoding="utf-8")
    findings = secret_scan.scan_paths([sample])
    assert findings, findings


def test_detects_yaml_password(tmp_path: Path) -> None:
    sample = tmp_path / "cfg.yaml"
    sample.write_text("mysql:\n  password: SuperSecretPass99\n", encoding="utf-8")
    findings = secret_scan.scan_paths([sample])
    assert findings, findings


def test_detects_json_token(tmp_path: Path) -> None:
    sample = tmp_path / "creds.json"
    sample.write_text('{"api_key": "abcdEFGHijklMNOP"}\n', encoding="utf-8")
    findings = secret_scan.scan_paths([sample])
    assert findings, findings


def test_detects_toml_secret(tmp_path: Path) -> None:
    sample = tmp_path / "app.toml"
    sample.write_text('secret = "toml-secret-value-01"\n', encoding="utf-8")
    findings = secret_scan.scan_paths([sample])
    assert findings, findings


def test_detects_compose_mysql_password(tmp_path: Path) -> None:
    sample = tmp_path / "compose.yaml"
    sample.write_text(
        "services:\n  db:\n    environment:\n      MYSQL_PASSWORD: LiveComposeSecret1\n",
        encoding="utf-8",
    )
    findings = secret_scan.scan_paths([sample])
    assert findings, findings


def test_detects_markdown_inline_assignment(tmp_path: Path) -> None:
    sample = tmp_path / "runbook.md"
    sample.write_text("Set TOKEN=leakytokenvalue99 before deploy.\n", encoding="utf-8")
    findings = secret_scan.scan_paths([sample])
    assert findings, findings


def test_detects_private_key_block(tmp_path: Path) -> None:
    sample = tmp_path / "key.pem.md"
    sample.write_text("-----BEGIN PRIVATE KEY-----\nMIIEvgIBADAN\n", encoding="utf-8")
    findings = secret_scan.scan_paths([sample])
    assert any("private key" in f.lower() for f in findings), findings


def test_detects_aws_access_key_id(tmp_path: Path) -> None:
    sample = tmp_path / "note.txt"
    sample.write_text("aws_key AKIAIOSFODNN7EXAMPLE\n", encoding="utf-8")
    findings = secret_scan.scan_paths([sample])
    assert findings, findings


def test_placeholder_and_empty_not_flagged(tmp_path: Path) -> None:
    sample = tmp_path / ".env.example"
    sample.write_text(
        "MYSQL_PASSWORD=changeme\nMODEL_API_KEY=\nPASSWORD=placeholder\n",
        encoding="utf-8",
    )
    assert secret_scan.scan_paths([sample]) == []


def test_identifier_reference_not_flagged(tmp_path: Path) -> None:
    sample = tmp_path / "ok.py"
    sample.write_text("password=self._password\napi_key = settings.api_key\n", encoding="utf-8")
    assert secret_scan.scan_paths([sample]) == []


def test_allowlist_remains_empty() -> None:
    assert secret_scan.ALLOWLIST_PATH_MARKERS == frozenset()


def test_deliverable_tree_is_clean() -> None:
    findings = secret_scan.scan_tree(PROJECT_ROOT)
    assert findings == [], "deliverable secret findings:\n" + "\n".join(findings)

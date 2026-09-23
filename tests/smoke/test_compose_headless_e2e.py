"""Step 14 SMOKE: Docker Compose headless E2E (SPEC §15 / §18.4)."""

from __future__ import annotations

import pytest

from scripts.compose_e2e import run_full_e2e


@pytest.mark.timeout(120)
def test_compose_headless_mysql_e2e_up_probe_down() -> None:
    report = run_full_e2e()
    assert report.get("cleaned_up") is True, f"compose cleanup failed: {report!r}"
    assert report.get("ok") is True, f"compose e2e failed: {report!r}"
    probe = report.get("probe") or {}
    assert probe.get("ok") is True
    query_probe = report.get("query_probe") or {}
    assert query_probe.get("ok") is True, f"query probe failed: {query_probe!r}"
    assert int(query_probe.get("row_count") or 0) > 0

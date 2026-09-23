"""RED: PRD AC-01..AC-11 matrix shell for V1 Release Gate (Step 14)."""

from __future__ import annotations

from typing import Any

EXPECTED_ACS: tuple[str, ...] = tuple(f"AC-{i:02d}" for i in range(1, 12))


def _gate() -> Any:
    import scripts.quality_gate as quality_gate

    return quality_gate


def test_ac_matrix_lists_all_prd_acceptance_criteria() -> None:
    gate = _gate()
    matrix = getattr(gate, "AC_MATRIX")
    ids = tuple(item["id"] if isinstance(item, dict) else item for item in matrix)
    assert ids == EXPECTED_ACS, f"expected {EXPECTED_ACS}, got {ids}"


def test_ac_matrix_entries_require_evidence_field() -> None:
    gate = _gate()
    matrix = getattr(gate, "AC_MATRIX")
    for item in matrix:
        assert isinstance(item, dict), "AC_MATRIX entries must be dicts with evidence"
        assert item.get("id") in EXPECTED_ACS
        evidence = item.get("evidence")
        assert isinstance(evidence, str) and evidence.strip(), (
            f"{item.get('id')} missing evidence pointer"
        )


def test_ac_matrix_has_no_skipped_or_deferred_v11_rows() -> None:
    gate = _gate()
    matrix = getattr(gate, "AC_MATRIX")
    for item in matrix:
        status = str(item.get("status", "")).lower()
        assert status not in {"skip", "deferred", "v1.1", "wontfix"}, (
            f"{item.get('id')} must not defer AC out of V1: {status!r}"
        )

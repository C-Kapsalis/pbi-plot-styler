"""y-combo naming and hierarchy.

Every y-combo group is named y<N>_combo_group, and every y<N>_* member is
parented to an existing group (``--rule y-combo``, F-y-combo-group-naming).
A report without y-combo groups is reported as skipped. Sample client:
tests/fixtures/universal.
"""
from __future__ import annotations

import pytest

from canvas_variants import VARIANTS
from cli_helpers import (  # noqa: F401  (fixtures imported for registration)
    EXIT_FINDINGS, EXIT_OK, check_json, of, report_context, universal,
)


def _skipped(payload: dict, part: str) -> bool:
    return any(part in note for note in payload.get("skipped", []))


@pytest.mark.layer3_5
@pytest.mark.visual_architecture
class TestYComboArchitecture:

    @pytest.mark.p1
    def test_y_combo_component_structure(self, report_context):
        payload = check_json(report_context, "y-combo")
        assert not _skipped(payload, "naming"), "the sample must hold a y-combo group"
        assert not of(payload, "YCOMBO-name"), payload["findings"]

    @pytest.mark.p1
    def test_parent_child_references(self, report_context):
        payload = check_json(report_context, "y-combo")
        assert not _skipped(payload, "hierarchy")
        assert not of(payload, "YCOMBO-orphan"), payload["findings"]


# -- variants (one defect each) ---------------------------------------------------
def test_badly_named_group(universal, report_context):
    VARIANTS["ycombo-bad-name"](universal)
    payload = check_json(report_context, "y-combo")
    assert payload["exit_code"] == EXIT_FINDINGS
    assert [f["subject"] for f in of(payload, "YCOMBO-name")] == ["Y1_Combo_Group"]
    # no group matches the pattern any more: the hierarchy half is skipped
    assert _skipped(payload, "hierarchy")
    assert not of(payload, "YCOMBO-orphan")


def test_orphaned_member(universal, report_context):
    VARIANTS["ycombo-orphan"](universal)
    payload = check_json(report_context, "y-combo")
    hits = of(payload, "YCOMBO-orphan")
    assert [h["subject"] for h in hits] == ["y2_values"]
    assert "<no parentGroupName>" in hits[0]["message"]


def test_report_without_groups_is_skipped(universal, report_context):
    VARIANTS["rule8-no-groups"](universal)
    payload = check_json(report_context, "y-combo")
    assert payload["exit_code"] == EXIT_OK
    assert _skipped(payload, "naming") and _skipped(payload, "hierarchy")

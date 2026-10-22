"""Canvas foundation rules.

  Rule 1  selector slicers carry an active visual-level f-Slicer gate   (--rule slicer-gates)
  Rule 3  answer bookmarks set the Analysis Category filter             (--rule category-filter)
  Rule 6  theme collection present, no hex literals in report.json      (--rule theme)
  Rule 8  the filter slicers live in a master group y_filters_group     (--rule filter-panel)

Rules 2, 4, 5 and 7 are not part of the tool.

The sample client is tests/fixtures/universal (deliverable -Report.Report;
the API-only M.Report is excluded from default sweeps). Each rule runs on a
tmp copy: check -> check --fix -> re-check.
"""
from __future__ import annotations

import json

import pytest

from canvas_variants import VARIANTS
from cli_helpers import (  # noqa: F401  (fixtures imported for registration)
    EXIT_FINDINGS, EXIT_OK, IDS, check_json, errors, of, report_context, run, universal,
)

pytestmark = [pytest.mark.layer3_5, pytest.mark.visual_architecture]

RULE1 = ("RULE1-visual", "RULE1-bookmark")
RULE3 = ("RULE3",)
RULE6 = ("THEME-NONE", "THEME-HEX")
RULE8 = ("RULE8-missing",)


def _critical(payload: dict, keys) -> list[dict]:
    want = {IDS[k] for k in keys}
    return [f for f in errors(payload) if f["id"] in want]


def _check_fix_recheck(report, rule: str, keys) -> None:
    """The imposition path: critical -> fix -> zero residual."""
    fix = run("check", report, "--rule", rule, "--fix")
    assert fix.exit_code == EXIT_OK, fix.output
    assert not _critical(check_json(report, rule), keys)


@pytest.mark.layer3_5
@pytest.mark.visual_architecture
class TestFoundationRules:

    @pytest.mark.p0
    def test_rule_1_field_parameter_f_slicer_filters(self, report_context):
        payload = check_json(report_context, "slicer-gates")
        assert not _critical(payload, RULE1), payload["findings"]

    @pytest.mark.p1
    def test_rule_3_analysis_category_filter_required(self, report_context):
        payload = check_json(report_context, "category-filter")
        assert not _critical(payload, RULE3), payload["findings"]

    @pytest.mark.p1
    def test_rule_6_theme_data_color_integration(self, report_context):
        payload = check_json(report_context, "theme")
        assert not _critical(payload, RULE6), payload["findings"]

    @pytest.mark.p1
    def test_rule_8_y_filters_group_master_container(self, report_context):
        payload = check_json(report_context, "filter-panel")
        assert not _critical(payload, RULE8), payload["findings"]

    @pytest.mark.p2
    def test_foundation_rules_comprehensive_report(self, report_context):
        """Reporting only (never fails): the summary covers 4 rules."""
        result = run("check", report_context, "--summary", "--json")
        payload = json.loads(result.output)
        summary = payload["compliance"]
        assert summary["total_rules"] == 4
        assert {r["rule"] for r in summary["rules"]} == {
            "slicer-gates", "category-filter", "theme", "filter-panel"}
        assert summary["compliant_rules"] == 4
        assert summary["compliance_percentage"] == 100.0
        assert summary["overall_compliance"] is True


# -- variants (check, then fix, then re-check) ------------------------------------
def test_rule_1_ungated_slicer_is_reported_then_fixed(universal, report_context):
    VARIANTS["rule1-ungated"](universal)
    payload = check_json(report_context, "slicer-gates")
    assert payload["exit_code"] == EXIT_FINDINGS
    hits = _critical(payload, RULE1)
    assert [f["id"] for f in hits] == [IDS["RULE1-visual"]]
    assert "x_selector_1_ungated" in hits[0]["subject"]
    _check_fix_recheck(report_context, "slicer-gates", RULE1)


def test_rule_3_bookmark_without_category_filter(universal, report_context):
    VARIANTS["rule3-missing"](universal)
    payload = check_json(report_context, "category-filter")
    hits = _critical(payload, RULE3)
    assert [f["subject"] for f in hits] == ["Spend | Clicks"]  # "Year" is menu chrome


@pytest.mark.parametrize("variant, expected", [
    ("theme-empty", ["THEME-NONE"]),
    ("theme-hex", ["THEME-HEX"]),
    ("theme-base-only", []),          # rule 6 stays compliant (warning only)
], ids=["theme-empty", "theme-hex", "theme-base-only"])
def test_rule_6_variants(universal, report_context, variant, expected):
    VARIANTS[variant](universal)
    payload = check_json(report_context, "theme")
    got = sorted(k for k in RULE6 if _critical(payload, [k]))
    assert got == expected


def test_rule_6_hex_finding_counts_matches(universal, report_context):
    VARIANTS["theme-hex"](universal)
    hit = of(check_json(report_context, "theme"), "THEME-HEX")
    assert len(hit) == 1 and "1" in hit[0]["message"] and "#1A2B3C" in hit[0]["message"]


def test_rule_8_renamed_master_group_is_fixed(universal, report_context):
    VARIANTS["rule8-renamed"](universal)
    payload = check_json(report_context, "filter-panel")
    assert [f["id"] for f in _critical(payload, RULE8)] == [IDS["RULE8-missing"]]
    _check_fix_recheck(report_context, "filter-panel", RULE8)
    pages = report_context / "definition" / "pages"
    renamed = list(pages.glob("*/visuals/y_filters_group/visual.json"))
    assert len(renamed) == 1
    group = json.loads(renamed[0].read_text(encoding="utf-8"))
    assert group["visualGroup"]["displayName"] == "y_filters_group"
    # the hidden outer group keeps its name; children and the bookmark follow
    assert list(pages.glob("*/visuals/edit_canvas/visual.json"))
    bm = (report_context / "definition" / "bookmarks" / "bA00000000000000000a.bookmark.json").read_text()
    assert '"g1"' not in bm and '"y_filters_group"' in bm


def test_rule_8_does_not_apply_without_groups(universal, report_context):
    VARIANTS["rule8-no-groups"](universal)
    payload = check_json(report_context, "filter-panel")
    assert payload["exit_code"] == EXIT_OK
    assert not payload["findings"]


# -- format selector, placeholders and y-combo details --------------------------------
def test_the_format_selector_reads_the_first_non_empty_literal(universal, report_context):
    path = report_context / "definition" / "report.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    flt = next(f for f in data["filterConfig"]["filters"] if f["field"]["Column"]["Property"] == "Selector Format")
    values = flt["filter"]["Where"][0]["Condition"]["In"]["Values"]
    flt["filter"]["Where"][0]["Condition"]["In"]["Values"] = [[{"Literal": {"Value": ""}}]] + values
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    payload = check_json(report_context, "format-selector")
    assert not of(payload, "FORMAT"), payload["findings"]


def test_a_missing_report_json_makes_the_format_rule_not_apply(universal, report_context):
    (report_context / "definition" / "report.json").unlink()
    payload = check_json(report_context, "format-selector")
    assert not of(payload, "FORMAT")
    assert any("report.json" in n for n in payload["skipped"])


def test_an_invalid_report_json_is_a_format_finding(universal, report_context):
    (report_context / "definition" / "report.json").write_text("{", encoding="utf-8")
    payload = check_json(report_context, "format-selector")
    assert of(payload, "FORMAT")


def test_a_y_combo_member_needs_a_name_after_the_prefix(universal, report_context):
    from canvas_variants import _edit, _load, _save, _v
    d = _load(_v(universal, "y1_values"))
    d["name"] = "y2_"
    d.pop("parentGroupName", None)
    _save(_v(universal, "y2_"), d)
    payload = check_json(report_context, "y-combo")
    assert "y2_" not in [f["subject"] for f in payload["findings"]]

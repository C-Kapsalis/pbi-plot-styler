"""The console output of the foundation rules and of ``rename-label``.

The rule reports carry the wording of the earlier report: the result block
per rule, the finding types and the guidance sentences.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from canvas_variants import VARIANTS
from cli_helpers import copy_fixture, load, run


@pytest.fixture
def client(tmp_path: Path) -> Path:
    return copy_fixture("universal", tmp_path)


def _report(client: Path) -> Path:
    return client / "-Report.Report"


# -- SCX70: the compliance report ---------------------------------------------------
def test_the_summary_prints_the_compliance_report(client):
    out = run("check", client, "--summary").stdout
    assert "\U0001F50D Template Foundation Rules Comprehensive Report:" in out
    assert "=" * 60 in out
    assert "# Template Foundation Rules Validation Report" in out
    assert "**Overall Compliance**: 100.0% (4/4 rules)" in out
    assert "**Violations**: 0 critical, 0 warnings" in out
    assert "## Rule #1: Field Parameter f-Slicer Filters ✅ PASS" in out
    assert "Components: 6/6 passed" in out
    assert "## Rule #3: Analysis Category Filter Required ✅ PASS" in out
    assert "## Rule #6: ThemeDataColor Integration ✅ PASS" in out
    assert "## Rule #8: y_filters_group Master Container ✅ PASS" in out
    assert "\U0001F4CA Summary:" in out
    assert "   Overall Compliance: True" in out
    assert "   Rules Passed: 4/4" in out
    assert "   Compliance Score: 100.0%" in out
    assert "   Critical Issues: 0" in out
    assert "   Warnings: 0" in out


def test_a_failing_rule_shows_its_finding_type_and_fix(client):
    VARIANTS["theme-hex"](client)
    out = run("check", client, "--summary").stdout
    assert "## Rule #6: ThemeDataColor Integration ❌ FAIL" in out
    assert "**\U0001F534 hardcoded_hex_colors** (report.json)" in out
    assert "- **Fix**: Replace each '#RGBHEX' literal in report.json with a " \
           "ThemeDataColor reference so customer rebrand flows through." in out


def test_the_report_prints_on_a_console_that_is_not_utf8(client):
    result = run("check", client, "--summary")
    assert "\U0001F50D" in result.stdout


# -- SCX71: the remediation hints ------------------------------------------------------
def test_the_json_fix_carries_the_original_guidance(client):
    VARIANTS["rule1-ungated"](client)
    payload = json.loads(run("check", client, "--summary", "--json").stdout)
    fixes = {f["id"]: f["fix"] for f in payload["findings"]}
    assert fixes["GAT001"] == (
        "In Power BI Desktop, select this slicer, open the Filters pane, drag the "
        "`f-Slicer` measure (from `f-Filters` or `w-Visuals Filters`) into 'Filters "
        "on this visual', and set the condition to >= 1 (or > 0).")


def test_the_theme_and_panel_hints():
    from pbi_plot_styler.rules import fix_hint
    assert fix_hint("THM002") == "Add themeCollection with proper theme references"
    assert fix_hint("THM003") == "Define customTheme to avoid hardcoded color values"
    assert fix_hint("PNL002") == "Convert to group container for proper hierarchy"
    assert fix_hint("CAT001").startswith("In Power BI Desktop, with this bookmark active")


# -- SCX72: the compliance keys --------------------------------------------------------
def test_the_compliance_keys_are_the_original_names(client):
    payload = json.loads(run("check", client, "--summary", "--json").stdout)
    compliance = payload["compliance"]
    assert list(compliance) == ["total_rules", "compliant_rules",
                                "compliance_percentage", "critical_violations",
                                "warning_violations", "info_violations",
                                "overall_compliance", "rules"]
    assert compliance["info_violations"] == 0


# -- SCX73: the per-rule result blocks --------------------------------------------------
def test_the_category_filter_prints_its_result_block(client):
    VARIANTS["rule3-missing"](client)
    out = run("check", client, "--rule", "category-filter").stdout
    assert "✅ Rule #3 Validation Results:" in out
    assert "   Components checked: 2" in out
    assert "   Compliant: False" in out
    assert "   Violations found:" in out
    assert "\U0001F534 Spend | Clicks: Page-level bookmark has no Analysis Category filter" \
        in out
    assert "Rule #3 critical violations found:" in out
    assert "  - Spend | Clicks: Page-level bookmark has no Analysis Category filter " \
           "(Expected: a filter in byName or byExpr targeting z-Map Dimension-Measure " \
           "Groupings[Analysis Category], Got: no such filter found)" in out


# -- SCX74: the filter-panel outcome ------------------------------------------------------
def test_the_filter_panel_fix_says_it_succeeded(client):
    VARIANTS["rule8-renamed"](client)
    out = run("check", client, "--rule", "filter-panel", "--fix").stdout
    assert ("Auto-fix SUCCEEDED — y_filters_group master container in place. "
            "Commit the modified report files.") in out


# -- SCX75: the category message ------------------------------------------------------------
def test_the_category_message(client):
    VARIANTS["rule3-missing"](client)
    out = run("check", client, "--rule", "category-filter").stdout
    assert ("Page-level bookmark has no Analysis Category filter (Expected: a filter "
            "in byName or byExpr targeting z-Map Dimension-Measure Groupings"
            "[Analysis Category], Got: no such filter found)") in out


# -- SCX76: the theme messages ----------------------------------------------------------------
def test_the_theme_messages(client):
    VARIANTS["theme-empty"](client)
    out = run("check", client, "--rule", "theme").stdout
    assert ("Report missing themeCollection configuration (Expected: themeCollection "
            "with baseTheme and customTheme, Got: null or missing)") in out
    assert ("No custom theme defined - may use hardcoded colors (Expected: customTheme "
            "configuration, Got: null or missing)") in out
    assert ("Report has no theme configuration. Without a base or custom theme, "
            "ThemeDataColor references cannot resolve and visuals fall back to Power "
            "BI defaults.") in out
    assert ("Theme collection is incomplete - missing: baseTheme, customTheme. Reports "
            "must declare both baseTheme and customTheme.") in out


def test_the_theme_hex_message(client):
    VARIANTS["theme-hex"](client)
    out = run("check", client, "--rule", "theme").stdout
    assert ("1 hard-coded hex color literal(s) in report.json (sample: \"#1A2B3C\") "
            "(Expected: ThemeDataColor references only, Got: 1 '#RGBHEX' literals)") in out


# -- SCX77: the panel messages ------------------------------------------------------------------
def test_the_panel_messages(client):
    VARIANTS["rule8-renamed"](client)
    out = run("check", client, "--rule", "filter-panel").stdout
    assert ("No y_filters_group master container found (Expected: y_filters_group group "
            "container (visualGroup.displayName == 'y_filters_group'), Got: not found)"
            ) in out


# -- SCX78: the visual positions -------------------------------------------------------------------
def test_the_position_messages(client):
    VARIANTS["position-missing-y"](client)
    out = run("check", client, "--rule", "visual-position").stdout
    assert "1 visual container(s) missing x or y position: " in out
    assert " visual container(s) missing x or y position: " in out


# -- SCX79: the y-combo messages --------------------------------------------------------------------
def test_the_y_combo_messages(client, tmp_path):
    VARIANTS["ycombo-bad-name"](client)
    out = run("check", client, "--rule", "y-combo").stdout
    assert "1 y-combo group(s) violate the y{N}_combo_group naming pattern: " in out
    other = copy_fixture("universal", tmp_path / "second")
    VARIANTS["ycombo-orphan"](other)
    out = run("check", other, "--rule", "y-combo").stdout
    assert ("1 y-combo child visual(s) orphaned (missing or invalid parentGroupName): "
            "y2_values → parent: <no parentGroupName>") in out
    assert "  - y2_values → parent: <no parentGroupName>" in out


# -- SCX83: the rename-label output ---------------------------------------------------------------------
def test_the_rename_label_output(tmp_path):
    from cli_helpers import copy_fixture as copy
    root = tmp_path / "client"
    copy("label-rename", root)
    result = run("rename-label", root, "--pair", "Cost/ New Customer", "Spend/ New Customer")
    lines = result.stdout.splitlines()
    assert lines[0] == '  2  "Cost/ New Customer" -> "Spend/ New Customer"'
    assert lines[1] == ""
    assert lines[2].startswith("DRY RUN: ")
    assert lines[3].startswith("    ")


# -- SCX84: a file with a byte-order mark ------------------------------------------------------------------
def test_a_bookmark_with_a_byte_order_mark_is_renamed(tmp_path):
    from cli_helpers import copy_fixture as copy
    root = tmp_path / "client"
    copy("label-rename", root)
    bookmark = next(root.rglob("*.bookmark.json"))
    bookmark.write_bytes(b"\xef\xbb\xbf" + bookmark.read_bytes())
    result = run("rename-label", root, "--pair", "Cost/ New Customer", "Spend/ New Customer",
                 "--apply")
    assert result.exit_code == 0, result.output
    assert bookmark.read_bytes().startswith(b"\xef\xbb\xbf")
    assert b"Spend/ New Customer" in bookmark.read_bytes()


# -- SCX85: a folder that does not exist -----------------------------------------------------------------------
def test_a_missing_folder_is_a_usage_error(tmp_path):
    result = run("rename-label", tmp_path / "nodir", "--pair", "a", "b")
    assert result.exit_code == 2
    assert "does not exist" in result.stderr

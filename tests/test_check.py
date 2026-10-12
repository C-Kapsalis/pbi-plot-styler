"""`pbi-plot-styler check`: integrity findings, surgical fixes, baselines.

Each test injects one specific defect into a copy of the (clean) brewbar
fixture and asserts the exact check id it must raise.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from pbi_plot_styler.check import CHECKS, FixRefused, fix_bookmark_text
from pbi_plot_styler.cli import main

DEF = Path("definition")
COMBO = DEF / "pages/overview/visuals/combo10/visual.json"
TABLE = DEF / "pages/shops/visuals/table20/visual.json"
BM01 = DEF / "bookmarks/bm01.bookmark.json"
BM02 = DEF / "bookmarks/bm02.bookmark.json"


def _check(path: Path, *args: str):
    return CliRunner().invoke(main, ["check", str(path), *args])


def _json(path: Path, *args: str) -> dict:
    result = _check(path, "--json", *args)
    payload = json.loads(result.output)
    assert payload["exit_code"] == result.exit_code
    return payload


def _ids(payload: dict) -> list[str]:
    return sorted(f["id"] for f in payload["findings"])


def _edit(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text, old
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def _edit_json(path: Path, mutate) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    mutate(data)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def test_clean_fixtures_pass(brewbar_report, report_dir):
    for report in (brewbar_report, report_dir):
        result = _check(report)
        assert result.exit_code == 0, result.output
        assert "0 error(s), 0 warning(s)" in result.output


def test_every_check_id_has_a_severity():
    assert all(sev in {"error", "warning"} for sev, _ in CHECKS.values())


# -- bindings ------------------------------------------------------------------
def test_renamed_measure_is_reported_in_field_and_query_ref(brewbar_report):
    _edit(brewbar_report / TABLE, '"Property": "Revenue v1.2 (Adj.)"', '"Property": "Revenue v1.3"')
    _edit(brewbar_report / TABLE, '"queryRef": "Sales Measures.Revenue v1.2 (Adj.)"',
          '"queryRef": "Sales Measures.Revenue v1.3"')
    payload = _json(brewbar_report)
    assert payload["exit_code"] == 1
    assert _ids(payload) == ["BND001", "BND002"]
    locations = {f["location"] for f in payload["findings"]}
    assert "Brewbar.Report/definition/pages/shops/visuals/table20/visual.json::Sales Measures[Revenue v1.3]" in locations


def test_filter_alias_is_resolved_through_from(brewbar_report):
    _edit(brewbar_report / DEF / "pages/overview/page.json",
          '"Source": "s"\n                          }\n                        },\n                        "Property": "City"',
          '"Source": "s"\n                          }\n                        },\n                        "Property": "Town"')
    payload = _json(brewbar_report)
    assert [f["subject"] for f in payload["findings"]] == ["Shops[Town]"]


def test_bindings_are_case_insensitive(brewbar_report):
    _edit(brewbar_report / TABLE, '"Entity": "Shops"', '"Entity": "shops"')
    assert _check(brewbar_report).exit_code == 0


def test_stale_metadata_selector_in_a_bookmark(brewbar_report):
    _edit(brewbar_report / BM01, '"metadata": "Sales Measures.Avg Ticket"', '"metadata": "Sales Measures.Avg Tix"')
    payload = _json(brewbar_report)
    assert _ids(payload) == ["BND002"]
    assert payload["findings"][0]["file"].endswith("bm01.bookmark.json")


def test_hierarchy_level_must_exist(brewbar_report):
    _edit(brewbar_report / TABLE, '"Level": "City"', '"Level": "Region"')
    _edit(brewbar_report / TABLE, '"queryRef": "Shops.Geography.City"', '"queryRef": "Shops.Geography.Region"')
    assert _ids(_json(brewbar_report)) == ["BND001", "BND002"]


def test_unresolvable_model_skips_bindings_but_runs_other_checks(brewbar_report):
    (brewbar_report / "definition.pbir").write_text(
        '{"version": "4.0", "datasetReference": {"byConnection": {}}}', encoding="utf-8"
    )
    _edit(brewbar_report / BM01, '"activeSection": "overview"', '"activeSection": "gone"')
    payload = _json(brewbar_report)
    assert payload["notes"] and "binding checks skipped" in payload["notes"][0]
    assert _ids(payload) == ["BMK003"]


# -- bookmarks -----------------------------------------------------------------
def test_unknown_options_key_is_found_and_fixed_surgically(brewbar_report):
    path = brewbar_report / BM02
    _edit(path, '"applyOnlyToTargetVisuals": true,', '"applyOnlyToTargetVisuals": true,\n    "preserveNewVisualVisibility": true,')
    before = path.read_text(encoding="utf-8")
    payload = _json(brewbar_report)
    assert _ids(payload) == ["BMK001"]
    assert payload["findings"][0]["fixable"] is True

    result = _check(brewbar_report, "--fix")
    assert result.exit_code == 0, result.output
    assert "removed options.preserveNewVisualVisibility" in result.output
    after = path.read_text(encoding="utf-8")
    expected = json.loads(before)
    del expected["options"]["preserveNewVisualVisibility"]
    assert json.loads(after) == expected
    # A surgical edit: exactly one line removed, nothing reformatted.
    assert after.splitlines() == [
        line for line in before.splitlines() if "preserveNewVisualVisibility" not in line
    ]


@pytest.mark.parametrize("position", ["first", "last", "sole"])
def test_options_key_removal_in_every_position(position):
    options = {
        "first": '{"bogus": [1, {"a": 2}], "suppressData": true}',
        "last": '{"suppressData": true, "bogus": "x"}',
        "sole": '{"bogus": null}',
    }[position]
    text = '{"name": "b", "options": ' + options + "}"
    new, done = fix_bookmark_text(text)
    assert done == ["removed options.bogus"]
    assert "bogus" not in json.loads(new)["options"]


def test_ambiguous_removal_is_refused():
    with pytest.raises(FixRefused):
        fix_bookmark_text('{"options": {"bogus": 1, "bogus": 1}}')


def test_string_integers_are_found_and_converted(brewbar_report):
    path = brewbar_report / BM01
    _edit(path, '"howCreated": 1', '"howCreated": "1"')
    _edit(path, '"Version": 2', '"Version": "2"')
    _edit(path, '"ComparisonKind": 0', '"ComparisonKind": "0"')
    before = path.read_bytes()
    payload = _json(brewbar_report)
    assert _ids(payload) == ["BMK002"] * 3

    result = _check(brewbar_report, "--fix")
    assert result.exit_code == 0, result.output
    after = path.read_bytes()
    assert after == before.replace(b'"1"', b"1", 1).replace(b'"2"', b"2", 1).replace(b'"0"', b"0", 1)


def test_non_numeric_string_integer_is_not_auto_fixed(brewbar_report):
    _edit(brewbar_report / BM01, '"howCreated": 1', '"howCreated": "User"')
    payload = _json(brewbar_report, "--fix")
    assert _ids(payload) == ["BMK002"]
    assert payload["findings"][0]["fixable"] is False
    assert payload["exit_code"] == 1


def test_missing_page_and_visual_references(brewbar_report):
    _edit(brewbar_report / BM02, '"activeSection": "shops"', '"activeSection": "gone"')
    _edit(brewbar_report / BM01, '"slicer10": {', '"ghost99": {')
    payload = _json(brewbar_report)
    assert _ids(payload) == ["BMK003", "BMK004"]
    subjects = {f["subject"] for f in payload["findings"]}
    assert subjects == {"activeSection:gone", "overview/ghost99"}


def test_section_for_a_missing_page(brewbar_report):
    _edit(brewbar_report / BM02, '"sections": {\n      "shops"', '"sections": {\n      "attic"')
    assert "BMK003" in _ids(_json(brewbar_report))


def test_bookmarks_json_lists_a_missing_bookmark(brewbar_report):
    _edit_json(brewbar_report / DEF / "bookmarks/bookmarks.json",
               lambda d: d["items"][1]["children"].append("bm99"))
    payload = _json(brewbar_report)
    assert _ids(payload) == ["BMK005"]
    assert payload["findings"][0]["subject"] == "bm99"


# -- field parameters, theme, JSON -------------------------------------------------
def test_overlapping_and_overflowing_field_parameter_slots(brewbar_report):
    def mutate(d):
        params = d["visual"]["query"]["queryState"]["Category"]["fieldParameters"]
        extra = json.loads(json.dumps(params[0]))
        extra["parameterExpr"]["Column"]["Expression"]["SourceRef"]["Entity"] = "x-Plot Specific 2"
        extra["parameterExpr"]["Column"]["Property"] = "x-Plot Specific 2"
        extra["length"] = 2
        params.append(extra)
    _edit_json(brewbar_report / COMBO, mutate)
    assert _ids(_json(brewbar_report)) == ["FPM001", "FPM002"]


def test_missing_theme_file_is_a_warning(brewbar_report):
    (brewbar_report / "StaticResources/SharedResources/BaseThemes/BrewbarBase.json").unlink()
    result = _check(brewbar_report)
    assert result.exit_code == 0  # advisory only
    assert "WARNING  THM001" in result.output


def test_invalid_json_is_reported(brewbar_report):
    (brewbar_report / TABLE).write_text("{ not json", encoding="utf-8")
    assert "JSN001" in _ids(_json(brewbar_report))


# -- baseline ---------------------------------------------------------------------
def test_baseline_accepts_known_findings_and_reports_healed(brewbar_report, tmp_path):
    baseline = tmp_path / "baseline.json"
    _edit(brewbar_report / BM02, '"activeSection": "shops"', '"activeSection": "gone"')
    assert _check(brewbar_report).exit_code == 1

    result = _check(brewbar_report, "--baseline", str(baseline), "--update-baseline")
    assert result.exit_code == 0, result.output
    assert json.loads(baseline.read_text())["findings"] == [
        {"id": "BMK003", "location": "Brewbar.Report/definition/bookmarks/bm02.bookmark.json::activeSection:gone"}
    ]
    assert _check(brewbar_report, "--baseline", str(baseline)).exit_code == 0

    # A new finding fails the run; the accepted one is not listed again.
    _edit(brewbar_report / BM01, '"slicer10": {', '"ghost99": {')
    result = _check(brewbar_report, "--baseline", str(baseline))
    assert result.exit_code == 1
    assert "BMK004" in result.output and "activeSection" not in result.output

    # Fix the accepted one: it is reported as healed.
    _edit(brewbar_report / BM02, '"activeSection": "gone"', '"activeSection": "shops"')
    payload = _json(brewbar_report, "--baseline", str(baseline))
    assert payload["healed"] == [
        {"id": "BMK003", "location": "Brewbar.Report/definition/bookmarks/bm02.bookmark.json::activeSection:gone"}
    ]


def test_missing_baseline_file_exits_2(brewbar_report, tmp_path):
    result = _check(brewbar_report, "--baseline", str(tmp_path / "nope.json"))
    assert result.exit_code == 2
    assert "--update-baseline" in result.output


def test_update_baseline_needs_a_file(brewbar_report):
    assert _check(brewbar_report, "--update-baseline").exit_code == 2


def test_check_a_directory_of_reports(tmp_path, project, brewbar):
    root = tmp_path / "all"
    root.mkdir()
    project.rename(root / "roastery")
    brewbar.rename(root / "brewbar")
    payload = _json(root)
    assert payload["reports"] == ["brewbar/Brewbar.Report", "roastery/Roastery.Report"]
    assert payload["exit_code"] == 0


def test_check_is_read_only_without_fix(brewbar_report):
    _edit(brewbar_report / BM01, '"howCreated": 1', '"howCreated": "1"')
    snapshot = {p: p.read_bytes() for p in brewbar_report.rglob("*") if p.is_file()}
    assert _check(brewbar_report).exit_code == 1
    assert snapshot == {p: p.read_bytes() for p in brewbar_report.rglob("*") if p.is_file()}

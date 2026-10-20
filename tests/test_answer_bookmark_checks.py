"""answer-bookmarks and bookmark-literals: guard, scope, counts and baselines.

Runs on the answer-bookmark sample report (``fixtures/spinout_02_db``) and the
picker-literals fixture, with one change per test.
"""
from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pytest

from answer_bookmark_variants import (
    CATEGORY_PREFIXES, INHERITED, MAIN_PAGE, MATRIX, NAVIGATOR, PIPELINE, ROW_DROPDOWNS, Y_ROWS,
    _bm, _edit, _matrix_page, _mx, _p, _section, no_prefix_match,
)
from cli_helpers import (
    BASELINES, FIXTURES, IDS, check_json, copy_fixture, dump, load, of, run, write_toml,
)

STAND_IN = FIXTURES / "spinout_02_db" / "-Insights.Report"


@pytest.fixture
def report(tmp_path: Path) -> Path:
    dest = tmp_path / "spinout_02_db" / "-Insights.Report"
    shutil.copytree(STAND_IN, dest)
    return dest


def _config(tmp_path: Path, **extra) -> Path:
    answer = {"prefixes": list(CATEGORY_PREFIXES), "inherited_fingerprints": list(INHERITED), **extra}
    return write_toml(tmp_path / "plotstyler.toml", {
        "answer_bookmarks": answer,
        "category": {"table": "z-Map Dimension-Measure Groupings", "column": "Analysis Category"},
        "placeholders": {"template_slot_table": "Helper Measures"},
    })


def _answers(report: Path, config: Path, *extra) -> dict:
    return check_json(report, "answer-bookmarks", *extra, config=config)


# -- SC10: the vacuity guard is never baselined -------------------------------------
def test_update_baseline_never_writes_the_guard(report, tmp_path):
    no_prefix_match(report)
    baseline = tmp_path / "floors.json"
    result = run("check", report, "--rule", "answer-bookmarks", "--config", _config(tmp_path),
                 "--baseline", baseline, "--update-baseline")
    assert result.exit_code == 1, result.output
    entries = json.loads(baseline.read_text(encoding="utf-8"))["findings"]
    assert IDS["vacuity"] not in {e["id"] for e in entries}


def test_update_baseline_drops_an_existing_guard_entry(report, tmp_path):
    baseline = tmp_path / "floors.json"
    dump(baseline, {"version": 1, "findings": [
        {"id": "ABK000", "location": "-Insights.Report/definition/bookmarks::prefixes"}]})
    result = run("check", report, "--rule", "answer-bookmarks", "--config", _config(tmp_path),
                 "--baseline", baseline, "--update-baseline")
    assert result.exit_code == 0, result.output
    assert "ABK000" not in baseline.read_text(encoding="utf-8")


def test_a_hand_written_guard_entry_does_not_accept_the_guard(report, tmp_path):
    no_prefix_match(report)
    config = _config(tmp_path)
    first = _answers(report, config)
    guard = of(first, "vacuity")[0]
    baseline = tmp_path / "floors.json"
    dump(baseline, {"version": 1, "findings": [{"id": guard["id"], "location": guard["location"]}]})
    payload = _answers(report, config, "--baseline", baseline)
    assert payload["exit_code"] == 1
    assert not of(payload, "vacuity")[0]["baselined"]


# -- SC26: every picker, dropdown and configured slicer must select something ---------
def _empty_picks(report: Path, container: str) -> None:
    def fn(d):
        sv = _section(d)["visualContainers"][container]["singleVisual"]
        flt = sv["objects"]["merge"]["general"][0]["properties"]["filter"]["filter"]
        flt["Where"][0]["Condition"]["In"]["Values"] = []
    _edit(_bm(report), fn)


CHART_PICKER = "0a0b0c0d0e0f01020304"


def _add_chart_only_picker(report: Path) -> None:
    """A main-page slicer on x-Selector 1 (no matrix parameter), captured empty."""
    src = _p(report, "pages", MAIN_PAGE, "visuals", "27ce5533384712bd1485", "visual.json")
    data = load(src)
    text = json.dumps(data).replace("x-Selector 2", "x-Selector 1").replace(
        "27ce5533384712bd1485", CHART_PICKER)
    folder = _p(report, "pages", MAIN_PAGE, "visuals", CHART_PICKER)
    folder.mkdir()
    (folder / "visual.json").write_text(text, encoding="utf-8")

    def fn(d):
        containers = _section(d)["visualContainers"]
        containers[CHART_PICKER] = json.loads(json.dumps(containers["27ce5533384712bd1485"]).replace(
            "x-Selector 2", "x-Selector 1"))
    _edit(_bm(report), fn)
    _empty_picks(report, CHART_PICKER)


def test_an_empty_row_dropdown_and_an_empty_chart_picker_are_each_reported(report, tmp_path):
    _empty_picks(report, ROW_DROPDOWNS[0])
    _add_chart_only_picker(report)
    payload = _answers(report, _config(tmp_path))
    subjects = sorted(f["subject"] for f in of(payload, "T6"))
    assert subjects == sorted([f"CRM Deals | Pipeline / {ROW_DROPDOWNS[0]}",
                               f"CRM Deals | Pipeline / {CHART_PICKER}"])


def test_bookmarks_build_output_passes_the_picker_check(tmp_path):
    builder = copy_fixture("bookmark-builder", tmp_path)
    report = builder / "Newsletter.Report"
    entries = tmp_path / "entries.json"
    dump(entries, [{"displayName": "Letters | One row", "pickers": {
        "y_selector_2": [{"table": "_Accounts", "column": "Account Name", "label": "Account"}],
        "x_selector_2": [{"table": "Newsletter Measures", "column": "Letters Sent #"}]}}])
    built = run("bookmarks", "build", entries, "--report", report, "--config", builder / "builder.toml",
                "--base", "bb45beb3422017d5f42c", "--group", "a348fcf214f494e5d34c")
    assert built.exit_code == 0, built.output
    config = write_toml(tmp_path / "check.toml", {"answer_bookmarks": {
        "prefixes": ["Letters |"], "main_page": "b0cec3dcab07d36ee0f9", "matrix": "9ae0cae20f0580ea0fc2"}})
    payload = check_json(report, "answer-bookmarks", config=config)
    assert not of(payload, "T6"), [f["message"] for f in of(payload, "T6")]


# -- SC27: an undeterminable row slicer stops the run -----------------------------------
def test_a_duplicated_row_slicer_is_a_setup_error(report, tmp_path):
    twin = "1a2b3c4d5e6f708192a3"
    shutil.copytree(_p(report, "pages", MAIN_PAGE, "visuals", Y_ROWS),
                    _p(report, "pages", MAIN_PAGE, "visuals", twin))
    result = run("check", report, "--rule", "answer-bookmarks", "--config", _config(tmp_path))
    assert result.exit_code == 2
    assert Y_ROWS in result.output and twin in result.output
    assert "[answer_bookmarks] slicers" in result.output


def test_a_matrix_without_a_row_parameter_notes_the_checks_not_run(report, tmp_path):
    def fn(d):
        d["visual"]["query"]["queryState"]["Rows"].pop("fieldParameters", None)
    _edit(_matrix_page(report), fn)
    payload = _answers(report, _config(tmp_path))
    note = next(n for n in payload["skipped"] if "row parameter" in n)
    assert "ABK004" in note and "ABK010" in note


def test_a_declared_parameter_without_a_slicer_is_named_in_values_only_mode(report, tmp_path):
    shutil.rmtree(_p(report, "pages", MAIN_PAGE, "visuals", "d93bbe99cd9d524857e7"))
    payload = _answers(report, _config(tmp_path))
    messages = [f["message"] for f in of(payload, "T9")]
    assert any("no known slicer for parameter 'x-Plot Specific 2'" in m for m in messages), messages
    assert not any("projections are" in m for m in messages)


# -- SC28: unreadable files fail the run ------------------------------------------------
def test_a_truncated_answer_bookmark_fails_the_run(report, tmp_path):
    path = _bm(report)
    path.write_text(path.read_text(encoding="utf-8")[:200], encoding="utf-8")
    payload = _answers(report, _config(tmp_path))
    assert payload["exit_code"] == 1
    assert [f["file"].split("/")[-1] for f in payload["findings"] if f["id"] == "JSN001"] == \
        [f"{PIPELINE}.bookmark.json"]
    assert not of(payload, "P2")


def test_a_truncated_main_page_visual_fails_the_run(report, tmp_path):
    path = _p(report, "pages", MAIN_PAGE, "visuals", NAVIGATOR, "visual.json")
    path.write_text("{", encoding="utf-8")
    payload = _answers(report, _config(tmp_path))
    assert payload["exit_code"] == 1
    assert any(f["id"] == "JSN001" for f in payload["findings"])


# -- SC29: --only-display-names accepts the builder's entries file ---------------------
LIT_PAGE, LIT_BOOKMARK = "5a5b5c5d5e5f50515253", "c1c1c1c1c1c1c1c1c1c1"


def test_only_display_names_accepts_an_entries_file(tmp_path):
    shop = copy_fixture("picker-literals", tmp_path)
    names = tmp_path / "names.json"
    dump(names, ["Sales | Revenue"])
    entries = tmp_path / "entries.json"
    dump(entries, [{"displayName": "Sales | Revenue", "pickers": {}}])
    a = check_json(shop / "Shop.Report", "bookmark-literals", "--only-display-names", names)
    b = check_json(shop / "Shop.Report", "bookmark-literals", "--only-display-names", entries)
    assert a["findings"] == b["findings"] and a["checked"] == b["checked"]
    bad = tmp_path / "bad.json"
    dump(bad, [{"name": "x"}])
    assert run("check", shop / "Shop.Report", "--rule", "bookmark-literals",
               "--only-display-names", bad).exit_code == 2


# -- SC30: what was checked -------------------------------------------------------------
def test_text_and_json_say_what_was_checked(report, tmp_path):
    config = _config(tmp_path)
    text = run("check", report, "--rule", "answer-bookmarks", "--config", config)
    assert "checked  answer-bookmarks: 2 answer bookmarks" in text.output
    payload = _answers(report, config)
    assert payload["checked"] == {"answer-bookmarks": {"answer bookmarks": 2}}


def test_literal_counts_are_printed(tmp_path):
    shop = copy_fixture("picker-literals", tmp_path)
    payload = check_json(shop / "Shop.Report", "bookmark-literals")
    counts = payload["checked"]["bookmark-literals"]
    assert counts["bookmarks scanned"] >= 1
    assert counts["literals checked"] == counts["literals resolved"] == 2


# -- SC31 / SC32: the configured baseline and healed entries ---------------------------
def test_the_configured_baseline_is_used(report, tmp_path):
    shutil.copy(BASELINES / "whole_page_bookmark_floors.json", tmp_path / "floors.json")
    config = _config(tmp_path, baseline="floors.json")
    payload = _answers(report, config)
    assert payload["exit_code"] == 0
    assert all(f["baselined"] for f in payload["findings"])


def test_a_missing_configured_baseline_is_a_usage_error(report, tmp_path):
    config = _config(tmp_path, baseline="absent.json")
    assert run("check", report, "--rule", "answer-bookmarks", "--config", config).exit_code == 2


def test_healed_counts_only_entries_of_this_run(report, tmp_path):
    baseline = tmp_path / "floors.json"
    shutil.copy(BASELINES / "whole_page_bookmark_floors.json", baseline)
    data = load(baseline)
    data["findings"].append({"id": "GAT001", "location": "-Insights.Report/x::y"})
    data["findings"].append({"id": "ABK007", "location": "Other.Report/definition/x::y"})
    dump(baseline, data)
    payload = _answers(report, _config(tmp_path), "--baseline", baseline)
    assert payload["healed"] == []


def test_a_healed_entry_prints_the_update_hint(report, tmp_path):
    baseline = tmp_path / "floors.json"
    shutil.copy(BASELINES / "whole_page_bookmark_floors.json", baseline)
    from answer_bookmark_variants import OWNERS
    _edit(_bm(report, OWNERS), lambda d: d["options"].update(targetVisualNames=[]))
    result = run("check", report, "--rule", "answer-bookmarks", "--config", _config(tmp_path),
                 "--baseline", baseline)
    assert "healed" in result.output
    assert "--update-baseline" in result.output


# -- SC40 / SC41: slot maps and messages -------------------------------------------------
def test_an_empty_slot_map_counts_as_missing_in_all_roles_mode(report, tmp_path):
    _edit(_bm(report), lambda d: _mx(d)["parameters"].update(Rows=[]))
    payload = _answers(report, _config(tmp_path, slot_mode="all-roles"))
    assert any("no Rows slot map" in f["message"] for f in of(payload, "T9"))


def test_the_slot_message_names_the_picks_outside_their_slots(report, tmp_path):
    _edit(_bm(report), lambda d: _mx(d)["parameters"]["Values"][1].update(index=0))
    payload = _answers(report, _config(tmp_path))
    message = of(payload, "T9")[0]["message"]
    assert "outside its slots:" in message and "[]" not in message.split("outside its slots:")[1]


def test_the_dropdown_message_says_when_the_dropdowns_hold_nothing(report, tmp_path):
    for dropdown in ROW_DROPDOWNS:
        _edit(_bm(report), lambda d, k=dropdown: _section(d)["visualContainers"].pop(k, None))
    payload = _answers(report, _config(tmp_path))
    assert "the dropdowns hold nothing" in of(payload, "T10")[0]["message"]


def test_summary_prints_a_fix_hint_under_each_finding(tmp_path):
    universal = copy_fixture("universal", tmp_path)
    report_json = universal / "-Report.Report" / "definition" / "report.json"
    data = load(report_json)
    data["themeCollection"].pop("customTheme")
    dump(report_json, data)
    result = run("check", universal, "--summary")
    lines = result.output.splitlines()
    finding_lines = [i for i, line in enumerate(lines) if line.startswith("  - ")]
    assert finding_lines
    assert all(lines[i + 1].startswith("    fix: ") for i in finding_lines)
    payload = json.loads(run("check", universal, "--summary", "--json").output)
    assert all(f.get("fix") for f in payload["findings"])


# -- SC42: bookmark-literals without a model ----------------------------------------------
def test_bookmark_literals_without_a_model_exits_2(report):
    result = run("check", report, "--rule", "bookmark-literals")
    assert result.exit_code == 2
    assert "--model" in result.output


# -- SC59: the navigator id form -------------------------------------------------------
@pytest.mark.parametrize("value", ["'0123456789ABCDEF0123'", "\"0123456789abcdef0123\""])
def test_the_navigator_reads_only_quoted_lower_case_ids(report, tmp_path, value):
    def fn(d):
        props = d["visual"]["objects"]["bookmarks"][0]["properties"]
        props["selectedBookmark"]["expr"]["Literal"]["Value"] = value
    _edit(_p(report, "pages", MAIN_PAGE, "visuals", NAVIGATOR, "visual.json"), fn)
    assert not of(_answers(report, _config(tmp_path)), "P2")


# -- SC60: fingerprints and registry names --------------------------------------------------
def test_a_non_ascii_fingerprint_is_found(report, tmp_path):
    def fn(d):
        _mx(d)["prototypeQuery"] = {"Version": 2, "Select": [
            {"Column": {"Expression": {"SourceRef": {"Entity": "_Campaigns"}}, "Property": "Καμπάνια"}}]}
    _edit(_bm(report), fn)
    payload = _answers(report, _config(tmp_path, inherited_fingerprints=["Καμπάνια"]))
    assert any("Καμπάνια" in f["message"] for f in of(payload, "T4"))


def test_a_quoted_and_a_bare_table_qualifier_register_the_same_row(tmp_path):
    shop = copy_fixture("picker-literals", tmp_path)
    table = next((shop / "Shop.SemanticModel" / "definition" / "tables").glob("y-Selector 2.tmdl"))
    text = table.read_text(encoding="utf-8")
    assert "NAMEOF('Stores'[Region])" in text.replace(" ", "") or "'Stores'[Region]" in text
    table.write_text(text.replace("'Stores'[Region]", "Stores[Region]"), encoding="utf-8")
    payload = check_json(shop / "Shop.Report", "bookmark-literals")
    assert payload["exit_code"] == 0, payload["findings"]

"""F-answer-bookmark-builder: ``bookmarks build CONFIG --report R``.

``newsletter_bookmarks.json`` is an example builder config for a fictional
newsletter report (``fixtures/bookmark-builder/Newsletter.Report``): five
answer bookmarks that each set every picker, the visibility of visuals and
groups, the analysis category, the date filter and the drill level. The
``test_self_test_*`` cases cover the single-pick and legacy-layout paths.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from ported_helpers import FIXTURES, copy_fixture, dump, load, run

BASE_ID = "bb45beb3422017d5f42c"
PAGE = "b0cec3dcab07d36ee0f9"
MATRIX, CHART = "9ae0cae20f0580ea0fc2", "a1548974e678537e1ad9"
GROUP = "a348fcf214f494e5d34c"
PICKERS = {
    "x_selector_1": "58c07edf66fcc668052a",
    "x_selector_2": "72770a4a26a76aa1bb30",
    "x_ps1": "aa1ab50e81c88b8f6c64",
    "x_ps2": "20a92fc55a409a14c50f",
    "y_selector_2": "4579e190f16af4b372c6",
    "y_selector_3": "71b3f5fce16278017dc3",
    "y_selector_4": "25daf9af719298e8d87d",
    "y_selector_5": "51bc0fa52fea898c4a86",
    "y_selector_6": "13236d898966a70ca101",
}
LETTERS_CONFIG = FIXTURES / "bookmark-builder" / "newsletter_bookmarks.json"
HEX20 = re.compile(r"^[0-9a-f]{20}$")


@pytest.fixture
def builder(tmp_path: Path) -> Path:
    return copy_fixture("bookmark-builder", tmp_path)


def _report(builder: Path) -> Path:
    return builder / "Newsletter.Report"


def _bookmarks_dir(builder: Path) -> Path:
    return _report(builder) / "definition" / "bookmarks"


def _build(builder: Path, config: Path, *extra):
    return run("bookmarks", "build", config, "--report", _report(builder),
               "--config", builder / "builder.toml", *extra)


def _write_config(tmp_path: Path, entries: list) -> Path:
    path = tmp_path / "entries.json"
    dump(path, entries)
    return path


def _by_display(builder: Path) -> dict[str, dict]:
    out = {}
    for f in sorted(_bookmarks_dir(builder).glob("*.bookmark.json")):
        data = load(f)
        out[data["displayName"]] = data
    return out


def _section(bm: dict) -> dict:
    st = bm["explorationState"]
    return st["sections"][st["activeSection"]]


def _general_filter(single: dict) -> dict:
    general = single["objects"]["merge"]["general"][0]
    return general["properties"]["filter"]["filter"]


def _picker_values(section: dict, vid: str) -> list[str]:
    flt = _general_filter(section["visualContainers"][vid]["singleVisual"])
    cond = next(w["Condition"]["In"] for w in flt["Where"] if "In" in w["Condition"])
    return [row[0]["Literal"]["Value"] for row in cond["Values"]]


def _cached_labels(section: dict, vid: str) -> list[str]:
    sv = section["visualContainers"][vid]["singleVisual"]
    return [i["displayName"] for i in sv.get("cachedFilterDisplayItems", [])]


def _literal(pick: dict) -> str:
    return f"'''{pick['table']}''[{pick['column']}]'"


def _files_snapshot(builder: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(_bookmarks_dir(builder).iterdir())}


# -- the example config -------------------------------------------------------
def test_letters_config_builds_one_bookmark_per_entry(builder):
    entries = load(LETTERS_CONFIG)
    result = _build(builder, LETTERS_CONFIG, "--base", BASE_ID, "--group", GROUP)
    assert result.exit_code == 0, result.output

    built = _by_display(builder)
    base = built.pop("Base | Template")
    assert set(built) == {e["displayName"] for e in entries}
    children = next(i for i in load(_bookmarks_dir(builder) / "bookmarks.json")["items"]
                    if i["name"] == GROUP)["children"]
    names = set()
    for entry in entries:
        bm = built[entry["displayName"]]
        assert HEX20.match(bm["name"]) and bm["name"] != base["name"]
        assert (_bookmarks_dir(builder) / f"{bm['name']}.bookmark.json").is_file()
        assert bm["name"] in children
        names.add(bm["name"])
        assert bm["options"]["targetVisualNames"] == []
        sec = _section(bm)
        for key, picks in entry["pickers"].items():
            assert _picker_values(sec, PICKERS[key]) == [_literal(p) for p in picks], key
            assert _cached_labels(sec, PICKERS[key]) == [p["label"] for p in picks], key
        for vid in entry["show"]:
            assert "display" not in sec["visualContainers"][vid]["singleVisual"], vid
        for vid in entry["hide"]:
            assert sec["visualContainers"][vid]["singleVisual"]["display"] == {"mode": "hidden"}, vid
        for gid in entry["show_groups"]:
            assert sec["visualContainerGroups"][gid]["isHidden"] is False
        for gid in entry["hide_groups"]:
            assert sec["visualContainerGroups"][gid]["isHidden"] is True
    assert len(names) == len(entries)  # every name fresh and distinct


def test_letters_config_category_date_and_drill(builder):
    entries = load(LETTERS_CONFIG)
    assert _build(builder, LETTERS_CONFIG, "--base", BASE_ID, "--group", GROUP).exit_code == 0
    built = _by_display(builder)
    for entry in entries:
        sec = _section(built[entry["displayName"]])
        by_expr = {f["name"]: f for f in sec["filters"]["byExpr"]}
        cat = next(w["Condition"]["In"] for w in by_expr["f_category"]["filter"]["Where"]
                   if "In" in w["Condition"])
        assert cat["Values"] == [[{"Literal": {"Value": f"'{entry['analysis_category']}'"}}]]

        date = by_expr["f_date"]
        assert date["howCreated"] == 1
        assert date["filter"]["Version"] == 2
        assert date["filter"]["From"][0]["Entity"] == "__Calendar"
        comp = date["filter"]["Where"][0]["Condition"]["Comparison"]
        assert comp["ComparisonKind"] == 0
        assert comp["Left"]["HierarchyLevel"]["Level"] == "Date"
        span = comp["Right"]["DateSpan"]
        assert "Now" in span["Expression"] and span["TimeUnit"] == 3

        chart = sec["visualContainers"][CHART]["singleVisual"]
        assert chart["activeProjections"]["Category"][0]["HierarchyLevel"]["Level"] == entry["drill_level"]


def test_letters_config_matrix_and_chart_captures(builder):
    entries = load(LETTERS_CONFIG)
    assert _build(builder, LETTERS_CONFIG, "--base", BASE_ID, "--group", GROUP).exit_code == 0
    built = _by_display(builder)
    for entry in entries:
        sec = _section(built[entry["displayName"]])
        mx = sec["visualContainers"][MATRIX]["singleVisual"]
        for gone in ("display", "expansionStates", "prototypeQuery"):
            assert gone not in mx, gone
        rows = entry["pickers"]["y_selector_2"]
        values = entry["pickers"]["x_selector_2"]
        assert [p["Column"]["Property"] for p in mx["projections"]["Rows"]] == [r["column"] for r in rows]
        assert [p["Column"]["Expression"]["SourceRef"]["Entity"] for p in mx["projections"]["Rows"]] == \
            [r["table"] for r in rows]
        assert [p["Measure"]["Property"] for p in mx["projections"]["Values"]] == [v["column"] for v in values]
        slot = mx["parameters"]["Values"][0]
        assert slot["expr"]["Column"]["Expression"]["SourceRef"]["Entity"] == "x-Selector 2"
        assert (slot["index"], slot["length"]) == (0, len(values))
        assert mx["parameters"]["Rows"][0]["expr"]["Column"]["Expression"]["SourceRef"]["Entity"] == "y-Selector 2"
        assert mx["activeProjections"] == {"Rows": [mx["projections"]["Rows"][0]]}

        chart = sec["visualContainers"][CHART]["singleVisual"]
        assert [p["Measure"]["Property"] for p in chart["projections"]["Y"]] == \
            [p["column"] for p in entry["pickers"]["x_ps1"]]
        assert [p["Measure"]["Property"] for p in chart["projections"]["Y2"]] == \
            [p["column"] for p in entry["pickers"]["x_ps2"]]
        # Series: no y plot picker in this config -> base capture kept; Category untouched
        assert chart["projections"]["Series"] == [
            {"Column": {"Expression": {"SourceRef": {"Entity": "_Legacy"}}, "Property": "Legacy Row"}}]
        assert chart["projections"]["Category"][0]["HierarchyLevel"]["Level"] == "Year"


def test_output_is_two_space_json_with_trailing_newline(builder):
    assert _build(builder, LETTERS_CONFIG, "--base", BASE_ID, "--group", GROUP).exit_code == 0
    for f in _bookmarks_dir(builder).glob("*.bookmark.json"):
        text = f.read_text(encoding="utf-8")
        assert text.endswith("\n")
        assert text == json.dumps(json.loads(text), indent=2) + "\n" or f.stem == BASE_ID


# -- self-test assertions ------------------------------------------------------
def test_self_test_one_values_pick(builder, tmp_path):
    pick = {"table": "Newsletter Measures", "column": "Letters Sent #", "label": "Letters Sent #"}
    cfg = _write_config(tmp_path, [{"displayName": "Letters | Self test", "pickers": {"x_selector_2": [pick]}}])
    result = _build(builder, cfg, "--base", BASE_ID, "--group", GROUP)
    assert result.exit_code == 0, result.output
    bm = _by_display(builder)["Letters | Self test"]
    sec = _section(bm)
    assert _picker_values(sec, PICKERS["x_selector_2"]) == ["'''Newsletter Measures''[Letters Sent #]'"]
    assert _cached_labels(sec, PICKERS["x_selector_2"]) == ["Letters Sent #"]
    assert bm["name"] != BASE_ID


def test_self_test_legacy_layout(builder, tmp_path):
    measures = [{"table": "Spend Measures", "column": c, "label": c} for c in ("Cost", "Clicks", "CPC")]
    row = [{"table": "_Campaigns", "column": "Campaign Name", "label": "Campaign"}]
    cfg = _write_config(tmp_path, [{
        "displayName": "Spend | Legacy", "analysis_category": "Spend",
        "pickers": {"x_selector_1": measures, "y_selector_2": row}}])
    result = _build(builder, cfg, "--base", BASE_ID, "--group", GROUP, "--legacy-layout")
    assert result.exit_code == 0, result.output
    sec = _section(_by_display(builder)["Spend | Legacy"])
    mx = sec["visualContainers"][MATRIX]["singleVisual"]
    assert len(mx["projections"]["Values"]) == 3
    assert len(mx["projections"]["Rows"]) == 1
    assert mx["orderBy"][0]["Expression"]["Measure"]["Property"] == "Cost"   # sorted on the first measure
    # unused axis pickers are cleared: Where [] and no cached items
    for key in ("x_selector_2", "x_ps1", "x_ps2"):
        sv = sec["visualContainers"][PICKERS[key]]["singleVisual"]
        assert _general_filter(sv)["Where"] == [], key
        assert not sv.get("cachedFilterDisplayItems"), key
    cat = next(f for f in sec["filters"]["byExpr"] if f["name"] == "f_category")
    assert cat["filter"]["Where"][0]["Condition"]["In"]["Values"] == [[{"Literal": {"Value": "'Spend'"}}]]


@pytest.mark.parametrize("n_measures,n_rows", [(2, 1), (3, 0), (3, 4)])
def test_legacy_layout_limits(builder, tmp_path, n_measures, n_rows):
    measures = [{"table": "Spend Measures", "column": f"M{i}", "label": f"M{i}"} for i in range(n_measures)]
    rows = [{"table": "_Campaigns", "column": f"R{i}", "label": f"R{i}"} for i in range(n_rows)]
    pickers = {"x_selector_1": measures}
    if rows:
        pickers["y_selector_2"] = rows
    cfg = _write_config(tmp_path, [{"displayName": "Spend | Bad", "pickers": pickers}])
    before = _files_snapshot(builder)
    result = _build(builder, cfg, "--base", BASE_ID, "--group", GROUP, "--legacy-layout")
    assert result.exit_code != 0
    assert _files_snapshot(builder) == before


# -- edits ---------------------------------------------------------------------
def test_target_visuals_are_honoured_and_key_never_removed(builder, tmp_path):
    cfg = _write_config(tmp_path, [
        {"displayName": "Letters | Scoped", "target_visuals": [CHART]},
        {"displayName": "Letters | Page"},
    ])
    assert _build(builder, cfg, "--base", BASE_ID, "--group", GROUP).exit_code == 0
    built = _by_display(builder)
    assert built["Letters | Scoped"]["options"]["targetVisualNames"] == [CHART]
    assert built["Letters | Page"]["options"]["targetVisualNames"] == []


def test_rows_are_mirrored_into_dropdowns(builder, tmp_path):
    rows = [{"table": "_Accounts", "column": "Account Name", "label": "Account"},
            {"table": "_Accounts", "column": "Account Service", "label": "Service"}]
    cfg = _write_config(tmp_path, [{"displayName": "Letters | Mirror", "pickers": {"y_selector_2": rows}}])
    assert _build(builder, cfg, "--base", BASE_ID, "--group", GROUP).exit_code == 0
    sec = _section(_by_display(builder)["Letters | Mirror"])
    assert _picker_values(sec, PICKERS["y_selector_3"]) == [_literal(rows[0])]
    assert _picker_values(sec, PICKERS["y_selector_4"]) == [_literal(rows[1])]


def test_more_row_picks_than_dropdowns_is_an_error(builder, tmp_path):
    rows = [{"table": "_Accounts", "column": f"C{i}", "label": f"C{i}"} for i in range(5)]
    cfg = _write_config(tmp_path, [{"displayName": "Letters | Too many", "pickers": {"y_selector_2": rows}}])
    before = _files_snapshot(builder)
    assert _build(builder, cfg, "--base", BASE_ID, "--group", GROUP).exit_code != 0
    assert _files_snapshot(builder) == before


def test_same_pick_twice_in_one_well_is_an_error(builder, tmp_path, ):
    # matrix Values well = x_ps1 + x_ps2 + x_selector_2 (the spec's default well map)
    toml = builder / "builder.toml"
    toml.write_text(toml.read_text(encoding="utf-8").replace(
        'matrix_values = ["x_selector_2"]', 'matrix_values = ["x_ps1", "x_ps2", "x_selector_2"]'),
        encoding="utf-8")
    pick = {"table": "Newsletter Measures", "column": "Letters Read #", "label": "Letters Read #"}
    cfg = _write_config(tmp_path, [{"displayName": "Letters | Dup", "pickers": {"x_ps1": [pick], "x_ps2": [pick]}}])
    before = _files_snapshot(builder)
    assert _build(builder, cfg, "--base", BASE_ID, "--group", GROUP).exit_code != 0
    assert _files_snapshot(builder) == before


def test_slot_map_with_several_value_pickers(builder, tmp_path):
    toml = builder / "builder.toml"
    toml.write_text(toml.read_text(encoding="utf-8").replace(
        'matrix_values = ["x_selector_2"]', 'matrix_values = ["x_ps1", "x_ps2", "x_selector_2"]'),
        encoding="utf-8")
    m = lambda c: {"table": "Newsletter Measures", "column": c, "label": c}  # noqa: E731
    cfg = _write_config(tmp_path, [{"displayName": "Letters | Slots", "pickers": {
        "x_ps1": [m("A")], "x_ps2": [m("B")], "x_selector_2": [m("C"), m("D")]}}])
    assert _build(builder, cfg, "--base", BASE_ID, "--group", GROUP).exit_code == 0
    mx = _section(_by_display(builder)["Letters | Slots"])["visualContainers"][MATRIX]["singleVisual"]
    assert [p["Measure"]["Property"] for p in mx["projections"]["Values"]] == ["A", "B", "C", "D"]
    assert [(s["expr"]["Column"]["Expression"]["SourceRef"]["Entity"], s["index"], s["length"])
            for s in mx["parameters"]["Values"]] == [
        ("x-Plot Specific 1", 0, 1), ("x-Plot Specific 2", 1, 1), ("x-Selector 2", 2, 2)]


def test_matrix_sort_defaults_to_direction_2(builder, tmp_path):
    cfg = _write_config(tmp_path, [{"displayName": "Letters | Sorted", "matrix_sort": {"measure": {
        "table": "Newsletter Measures", "column": "Letters Sent #"}}}])
    assert _build(builder, cfg, "--base", BASE_ID, "--group", GROUP).exit_code == 0
    mx = _section(_by_display(builder)["Letters | Sorted"])["visualContainers"][MATRIX]["singleVisual"]
    assert mx["orderBy"][0]["Direction"] == 2
    assert mx["orderBy"][0]["Expression"]["Measure"]["Property"] == "Letters Sent #"


def test_unhide_matrix_false_leaves_matrix_capture(builder, tmp_path):
    base = load(_bookmarks_dir(builder) / f"{BASE_ID}.bookmark.json")
    cfg = _write_config(tmp_path, [{"displayName": "Letters | Keep matrix", "unhide_matrix": False}])
    assert _build(builder, cfg, "--base", BASE_ID, "--group", GROUP).exit_code == 0
    sec = _section(_by_display(builder)["Letters | Keep matrix"])
    assert sec["visualContainers"][MATRIX] == _section(base)["visualContainers"][MATRIX]


def test_empty_wells_remove_projection_keys(builder, tmp_path):
    toml = builder / "builder.toml"
    toml.write_text(toml.read_text(encoding="utf-8").replace(
        'matrix_rows = ["y_selector_2"], matrix_values = ["x_selector_2"]',
        'matrix_rows = ["y_none"], matrix_values = ["x_none"]'), encoding="utf-8")
    cfg = _write_config(tmp_path, [{"displayName": "Letters | Empty"}])
    assert _build(builder, cfg, "--base", BASE_ID, "--group", GROUP).exit_code == 0
    mx = _section(_by_display(builder)["Letters | Empty"])["visualContainers"][MATRIX]["singleVisual"]
    for key in ("projections", "parameters", "activeProjections"):
        assert key not in mx, key


@pytest.mark.parametrize("entry", [
    {"pickers": {"x_selector_2": []}},                                     # no displayName
    {"displayName": "Letters | Bad picker", "pickers": {"x_unknown": []}},   # picker not configured
    {"displayName": "Letters | Bad group", "group": "no-such-group"},
])
def test_invalid_entries_are_errors(builder, tmp_path, entry):
    cfg = _write_config(tmp_path, [entry])
    before = _files_snapshot(builder)
    assert _build(builder, cfg, "--base", BASE_ID, "--group", GROUP).exit_code != 0
    assert _files_snapshot(builder) == before


def test_picker_missing_from_captured_section_is_an_error(builder, tmp_path):
    def drop(data):
        del data["explorationState"]["sections"][PAGE]["visualContainers"][PICKERS["x_selector_1"]]
    path = _bookmarks_dir(builder) / f"{BASE_ID}.bookmark.json"
    data = load(path)
    drop(data)
    dump(path, data)
    pick = {"table": "T", "column": "C", "label": "C"}
    cfg = _write_config(tmp_path, [{"displayName": "Letters | Missing", "pickers": {"x_selector_1": [pick]}}])
    assert _build(builder, cfg, "--base", BASE_ID, "--group", GROUP).exit_code != 0


@pytest.mark.parametrize("entry,filter_name", [
    ({"displayName": "Letters | No cat", "analysis_category": "Spend"}, "f_category"),
    ({"displayName": "Letters | No date", "date_filter": "this_year"}, "f_date"),
])
def test_missing_filter_is_an_error(builder, tmp_path, entry, filter_name):
    path = _bookmarks_dir(builder) / f"{BASE_ID}.bookmark.json"
    data = load(path)
    sec = data["explorationState"]["sections"][PAGE]
    sec["filters"]["byExpr"] = [f for f in sec["filters"]["byExpr"] if f["name"] != filter_name]
    dump(path, data)
    cfg = _write_config(tmp_path, [entry])
    assert _build(builder, cfg, "--base", BASE_ID, "--group", GROUP).exit_code != 0


def test_per_entry_group_wins(builder, tmp_path):
    other = "ee6dbf6c2baa5d098c14"
    cfg = _write_config(tmp_path, [{"displayName": "Letters | Other", "group": other}])
    assert _build(builder, cfg, "--base", BASE_ID, "--group", GROUP).exit_code == 0
    name = _by_display(builder)["Letters | Other"]["name"]
    items = {i["name"]: i for i in load(_bookmarks_dir(builder) / "bookmarks.json")["items"]}
    assert name in items[other]["children"]
    assert name not in items[GROUP]["children"]


# -- re-render mode ------------------------------------------------------------
def test_keep_ids_rerenders_in_place(builder, tmp_path):
    pick = {"table": "Newsletter Measures", "column": "Letters Sent #", "label": "Letters Sent #"}
    cfg = _write_config(tmp_path, [{"displayName": "Letters | Rerender", "pickers": {"x_selector_2": [pick]}}])
    assert _build(builder, cfg, "--base", BASE_ID, "--group", GROUP).exit_code == 0
    first = _by_display(builder)["Letters | Rerender"]["name"]

    pick2 = {"table": "Newsletter Measures", "column": "Letters Read #", "label": "Letters Read #"}
    cfg2 = _write_config(tmp_path, [
        {"displayName": "Letters | Rerender", "pickers": {"x_selector_2": [pick2]},
         "clear_filters": ["f_legacy"]},
        {"displayName": "Letters | Brand new"},
    ])
    assert _build(builder, cfg2, "--base", BASE_ID, "--group", GROUP, "--keep-ids").exit_code == 0
    built = _by_display(builder)
    again = built["Letters | Rerender"]
    assert again["name"] == first
    sec = _section(again)
    assert _picker_values(sec, PICKERS["x_selector_2"]) == [_literal(pick2)]
    legacy_section = next(f for f in sec["filters"]["byExpr"] if f["name"] == "f_legacy")
    legacy_report = next(f for f in again["explorationState"]["filters"]["byExpr"] if f["name"] == "f_legacy")
    assert "filter" not in legacy_section and "filter" not in legacy_report
    children = next(i for i in load(_bookmarks_dir(builder) / "bookmarks.json")["items"]
                    if i["name"] == GROUP)["children"]
    assert children[0] == built["Letters | Brand new"]["name"]
    assert children.count(first) == 1


def test_a_bookmark_built_without_a_group_is_registered_at_the_top_level(builder):
    result = _build(builder, LETTERS_CONFIG, "--base", BASE_ID)
    assert result.exit_code == 0, result.output
    built = _by_display(builder)
    built.pop("Base | Template")
    top = [i["name"] for i in load(_bookmarks_dir(builder) / "bookmarks.json")["items"]]
    assert built and all(bm["name"] in top for bm in built.values())
    assert "registered" in result.output
    again = _build(builder, LETTERS_CONFIG, "--base", BASE_ID, "--keep-ids")
    assert again.exit_code == 0, again.output
    top_again = [i["name"] for i in load(_bookmarks_dir(builder) / "bookmarks.json")["items"]]
    assert sorted(top_again) == sorted(top)


def _picker_values_or_none(section: dict, vid: str) -> list[str]:
    flt = _general_filter(section["visualContainers"][vid]["singleVisual"])
    conds = [w["Condition"]["In"] for w in (flt or {}).get("Where") or [] if "In" in w["Condition"]]
    return [row[0]["Literal"]["Value"] for row in conds[0]["Values"]] if conds else []


def test_an_explicit_dropdown_for_one_row_still_mirrors_the_others(builder, tmp_path):
    rows = [{"table": "_Accounts", "column": "Account Name", "label": "Account"},
            {"table": "_Accounts", "column": "Account Service", "label": "Service"}]
    cfg = _write_config(tmp_path, [{"displayName": "Letters | Mixed", "pickers": {
        "y_selector_2": rows, "y_selector_3": [rows[0]]}}])
    result = _build(builder, cfg, "--base", BASE_ID, "--group", GROUP)
    assert result.exit_code == 0, result.output
    sec = _section(_by_display(builder)["Letters | Mixed"])
    assert _picker_values(sec, PICKERS["y_selector_3"]) == [_literal(rows[0])]
    # the row the explicit dropdown does not hold goes to the next free dropdown
    assert _picker_values(sec, PICKERS["y_selector_4"]) == [_literal(rows[1])]


def test_dropdowns_without_a_row_lose_the_base_bookmark_pick(builder, tmp_path):
    row = {"table": "_Accounts", "column": "Account Name", "label": "Account"}
    cfg = _write_config(tmp_path, [{"displayName": "Letters | One row",
                                    "pickers": {"y_selector_2": [row]}}])
    assert _build(builder, cfg, "--base", BASE_ID, "--group", GROUP).exit_code == 0
    sec = _section(_by_display(builder)["Letters | One row"])
    assert _picker_values(sec, PICKERS["y_selector_3"]) == [_literal(row)]
    for key in ("y_selector_4", "y_selector_5", "y_selector_6"):
        assert _picker_values_or_none(sec, PICKERS[key]) == [], key

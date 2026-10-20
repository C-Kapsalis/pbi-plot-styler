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

from cli_helpers import FIXTURES, copy_fixture, dump, load, run

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


def test_dropdowns_without_a_row_keep_the_base_bookmark_pick(builder, tmp_path):
    # a captured dropdown is never left selecting nothing (ABK006)
    row = {"table": "_Accounts", "column": "Account Name", "label": "Account"}
    cfg = _write_config(tmp_path, [{"displayName": "Letters | One row",
                                    "pickers": {"y_selector_2": [row]}}])
    assert _build(builder, cfg, "--base", BASE_ID, "--group", GROUP).exit_code == 0
    sec = _section(_by_display(builder)["Letters | One row"])
    assert _picker_values(sec, PICKERS["y_selector_3"]) == [_literal(row)]
    base_pick = _literal({"table": "Old Measures", "column": "Legacy Metric #"})
    for key in ("y_selector_4", "y_selector_5", "y_selector_6"):
        assert _picker_values_or_none(sec, PICKERS[key]) == [base_pick], key


# -- legacy layout: values slicers --------------------------------------------------
VALUES_2, VALUES_3 = "e1a2b3c4d5e6f7a8b9c0", "f0e9d8c7b6a5f4e3d2c1"
MEASURES = [{"table": "Spend Measures", "column": c, "label": c} for c in ("Cost", "Clicks", "CPC")]
CAMPAIGN = {"table": "_Campaigns", "column": "Campaign Name", "label": "Campaign"}
CHANNEL = {"table": "_Campaigns", "column": "Channel", "label": "Channel"}


def _column(table: str, column: str) -> dict:
    return {"Column": {"Expression": {"SourceRef": {"Entity": table}}, "Property": column}}


def _values_slicer(table: str, column: str) -> dict:
    """A captured slicer listing the values of one column, with a preselection."""
    return {"singleVisual": {
        "visualType": "slicer",
        "projections": {"Values": [{**_column(table, column), "queryRef": f"{table}.{column}"}]},
        "activeProjections": {"Values": [_column(table, column)]},
        "objects": {"merge": {"general": [{"properties": {"filter": {"filter": {
            "Version": 2,
            "From": [{"Name": "i", "Entity": table, "Type": 0}],
            "Where": [{"Condition": {"In": {
                "Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": "i"}},
                                            "Property": column}}],
                "Values": [[{"Literal": {"Value": "'Spring'"}}]]}}}]}}}}]}},
    }, "filters": {"byExpr": [
        {"name": "values_column", "expression": _column(table, column)},
        {"name": "values_measure", "expression": {"Measure": {
            "Expression": {"SourceRef": {"Entity": "Spend Measures"}}, "Property": "Cost"}}},
    ]}}


def _with_values_slicers(builder: Path, *, keys: dict[str, str], capture: tuple[str, ...]) -> None:
    """Register ``keys`` (picker key -> visual id) and capture ``capture`` in the base."""
    toml = builder / "builder.toml"
    extra = ", ".join(f'{k} = "{v}"' for k, v in keys.items())
    toml.write_text(toml.read_text(encoding="utf-8").replace(
        'pickers = {', f"pickers = {{{extra}, "), encoding="utf-8")
    base = _bookmarks_dir(builder) / f"{BASE_ID}.bookmark.json"
    data = load(base)
    containers = _section(data)["visualContainers"]
    for vid in capture:
        containers[vid] = _values_slicer("_Issues", "Issue Topic")
    dump(base, data)


def _legacy(builder: Path, tmp_path: Path, pickers: dict, *extra) -> dict:
    cfg = _write_config(tmp_path, [{"displayName": "Spend | Legacy", "analysis_category": "Spend",
                                    "pickers": pickers}])
    result = _build(builder, cfg, "--base", BASE_ID, "--group", GROUP, "--legacy-layout", *extra)
    assert result.exit_code == 0, result.output
    return result


def _slicer(builder: Path, vid: str) -> dict:
    return _section(_by_display(builder)["Spend | Legacy"])["visualContainers"][vid]


def test_a_values_slicer_follows_its_dimension_pickers_first_pick(builder, tmp_path):
    _with_values_slicers(builder, keys={"y_values_slicer_2": VALUES_2}, capture=(VALUES_2,))
    _legacy(builder, tmp_path, {"x_selector_1": MEASURES, "y_selector_2": [CAMPAIGN, CHANNEL]})
    slicer = _slicer(builder, VALUES_2)
    single = slicer["singleVisual"]
    assert _general_filter(single)["Where"] == []
    first = single["projections"]["Values"][0]
    assert first["Column"] == _column("_Campaigns", "Campaign Name")["Column"]
    assert first["queryRef"] == "_Issues.Issue Topic"  # other properties are left alone
    assert single["activeProjections"]["Values"][0] == _column("_Campaigns", "Campaign Name")
    by_name = {f["name"]: f["expression"] for f in slicer["filters"]["byExpr"]}
    assert by_name["values_column"] == _column("_Campaigns", "Campaign Name")
    # never a measure: the measure entry is untouched and nothing points at Cost
    assert by_name["values_measure"]["Measure"]["Property"] == "Cost"
    assert "Spend Measures" not in json.dumps(single)


def test_a_values_slicer_without_dimension_picks_is_only_cleared(builder, tmp_path):
    # one row: it is mirrored into y_selector_3, and y_selector_4 is left with no pick
    _with_values_slicers(builder, keys={"y_values_slicer_2": VALUES_2, "y_values_slicer_4": VALUES_3},
                         capture=(VALUES_2, VALUES_3))
    _legacy(builder, tmp_path, {"x_selector_1": MEASURES, "y_selector_2": [CAMPAIGN]})
    untouched = _values_slicer("_Issues", "Issue Topic")["singleVisual"]
    single = _slicer(builder, VALUES_3)["singleVisual"]
    assert _general_filter(single)["Where"] == []
    assert single["projections"] == untouched["projections"]
    assert single["activeProjections"] == untouched["activeProjections"]


def test_values_slicer_keys_are_not_pickers(builder, tmp_path):
    _with_values_slicers(builder, keys={"y_values_slicer_2": VALUES_2}, capture=(VALUES_2,))
    cfg = _write_config(tmp_path, [{"displayName": "Spend | Legacy", "pickers": {
        "x_selector_1": MEASURES, "y_selector_2": [CAMPAIGN], "y_values_slicer_2": [CHANNEL]}}])
    result = _build(builder, cfg, "--base", BASE_ID, "--group", GROUP, "--legacy-layout")
    assert result.exit_code == 2
    assert "y_values_slicer_2" in result.output


def test_a_missing_values_slicer_visual_or_key_is_skipped(builder, tmp_path):
    # key registered but not captured in the base; y_values_slicer_3 not registered at all
    _with_values_slicers(builder, keys={"y_values_slicer_2": VALUES_2}, capture=())
    _legacy(builder, tmp_path, {"x_selector_1": MEASURES, "y_selector_2": [CAMPAIGN],
                                "y_selector_3": [CHANNEL]})
    containers = _section(_by_display(builder)["Spend | Legacy"])["visualContainers"]
    assert VALUES_2 not in containers


def test_values_slicers_are_untouched_outside_the_legacy_layout(builder, tmp_path):
    _with_values_slicers(builder, keys={"y_values_slicer_2": VALUES_2}, capture=(VALUES_2,))
    cfg = _write_config(tmp_path, [{"displayName": "Spend | Legacy",
                                    "pickers": {"y_selector_2": [CAMPAIGN]}}])
    assert _build(builder, cfg, "--base", BASE_ID, "--group", GROUP).exit_code == 0
    assert _slicer(builder, VALUES_2) == _values_slicer("_Issues", "Issue Topic")


def test_a_legacy_rerender_keeps_bom_and_crlf(builder, tmp_path):
    _with_values_slicers(builder, keys={"y_values_slicer_2": VALUES_2}, capture=(VALUES_2,))
    pickers = {"x_selector_1": MEASURES, "y_selector_2": [CAMPAIGN]}
    _legacy(builder, tmp_path, pickers)
    built = next(p for p in _bookmarks_dir(builder).glob("*.bookmark.json")
                 if load(p)["displayName"] == "Spend | Legacy")
    text = built.read_bytes().decode("utf-8").replace("\n", "\r\n")
    built.write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))
    _legacy(builder, tmp_path, pickers, "--keep-ids")
    raw = built.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    assert b"\n" not in raw.replace(b"\r\n", b"")
    single = json.loads(raw.decode("utf-8-sig"))
    section = _section(single)["visualContainers"][VALUES_2]["singleVisual"]
    assert _general_filter(section)["Where"] == []


def test_a_legacy_dry_run_writes_nothing(builder, tmp_path):
    _with_values_slicers(builder, keys={"y_values_slicer_2": VALUES_2}, capture=(VALUES_2,))
    before = _files_snapshot(builder)
    _legacy(builder, tmp_path, {"x_selector_1": MEASURES, "y_selector_2": [CAMPAIGN]}, "--dry-run")
    assert _files_snapshot(builder) == before


# -- slot expressions, wells and captures -----------------------------------------
def _matrix(builder: Path, display: str) -> dict:
    return _section(_by_display(builder)[display])["visualContainers"][MATRIX]["singleVisual"]


def _slot_column(slot: dict) -> tuple[str, str]:
    column = slot["expr"]["Column"]
    return column["Expression"]["SourceRef"]["Entity"], column["Property"]


def _set_wells(builder: Path, old: str, new: str) -> None:
    toml = builder / "builder.toml"
    text = toml.read_text(encoding="utf-8")
    assert old in text
    toml.write_text(text.replace(old, new), encoding="utf-8")


def _edit_base(builder: Path, mutate, bookmark_id: str = BASE_ID) -> None:
    path = _bookmarks_dir(builder) / f"{bookmark_id}.bookmark.json"
    data = load(path)
    mutate(data)
    dump(path, data)


def test_slots_name_the_parameter_display_column_not_the_fields_column(builder):
    # the picker slicers filter on "<parameter> Fields"; the slot names "<parameter>"
    assert _build(builder, LETTERS_CONFIG, "--base", BASE_ID, "--group", GROUP).exit_code == 0
    built = _by_display(builder)
    built.pop("Base | Template")
    for bm in built.values():
        sec = _section(bm)
        mx = sec["visualContainers"][MATRIX]["singleVisual"]
        assert _slot_column(mx["parameters"]["Values"][0]) == ("x-Selector 2", "x-Selector 2")
        assert _slot_column(mx["parameters"]["Rows"][0]) == ("y-Selector 2", "y-Selector 2")
        chart = sec["visualContainers"][CHART]["singleVisual"]
        assert _slot_column(chart["parameters"]["Y"][0]) == ("x-Plot Specific 1", "x-Plot Specific 1")
        assert _slot_column(chart["parameters"]["Y2"][0]) == ("x-Plot Specific 2", "x-Plot Specific 2")


def test_legacy_slots_name_the_parameter_display_column(builder, tmp_path):
    row = [{"table": "_Campaigns", "column": "Campaign Name", "label": "Campaign"}]
    measures = [{"table": "Spend Measures", "column": c, "label": c} for c in ("Cost", "Clicks", "CPC")]
    cfg = _write_config(tmp_path, [{"displayName": "Spend | Legacy", "analysis_category": "Spend",
                                    "pickers": {"x_selector_1": measures, "y_selector_2": row}}])
    assert _build(builder, cfg, "--base", BASE_ID, "--group", GROUP, "--legacy-layout").exit_code == 0
    mx = _matrix(builder, "Spend | Legacy")
    assert _slot_column(mx["parameters"]["Values"][0]) == ("x-Selector 1", "x-Selector 1")
    assert _slot_column(mx["parameters"]["Rows"][0]) == ("y-Selector 2", "y-Selector 2")


def test_wells_take_only_the_entrys_own_picks(builder, tmp_path):
    # every base picker holds the same placeholder; only the named picker feeds the well
    _set_wells(builder, 'matrix_values = ["x_selector_2"]',
               'matrix_values = ["x_ps1", "x_ps2", "x_selector_2"]')
    pick = {"table": "Old Measures", "column": "Legacy Metric #", "label": "Legacy Metric #"}
    cfg = _write_config(tmp_path, [{"displayName": "Letters | Own", "pickers": {"x_selector_2": [pick]}}])
    result = _build(builder, cfg, "--base", BASE_ID, "--group", GROUP)
    assert result.exit_code == 0, result.output
    mx = _matrix(builder, "Letters | Own")
    assert [p["Measure"]["Property"] for p in mx["projections"]["Values"]] == ["Legacy Metric #"]
    sec = _section(_by_display(builder)["Letters | Own"])
    # an unnamed picker keeps its saved selection on the slicer itself
    assert _picker_values(sec, PICKERS["x_ps1"]) == [_literal(pick)]


def test_matrix_wells_write_a_zero_length_slot_for_a_picker_without_picks(builder, tmp_path):
    _set_wells(builder, 'matrix_values = ["x_selector_2"]',
               'matrix_values = ["x_ps1", "x_ps2", "x_selector_2"]')
    m = {"table": "Newsletter Measures", "column": "A", "label": "A"}
    cfg = _write_config(tmp_path, [{"displayName": "Letters | Zero", "pickers": {
        "x_ps1": [], "x_selector_2": [m]}}])
    assert _build(builder, cfg, "--base", BASE_ID, "--group", GROUP).exit_code == 0
    slots = _matrix(builder, "Letters | Zero")["parameters"]["Values"]
    assert [(_slot_column(s)[0], s["index"], s["length"]) for s in slots] == [
        ("x-Plot Specific 1", 0, 0), ("x-Plot Specific 2", 0, 0), ("x-Selector 2", 0, 1)]


def test_a_chart_picker_named_with_no_picks_leaves_one_empty_slot(builder, tmp_path):
    cfg = _write_config(tmp_path, [{"displayName": "Letters | No Y", "pickers": {"x_ps1": []}}])
    assert _build(builder, cfg, "--base", BASE_ID, "--group", GROUP).exit_code == 0
    chart = _section(_by_display(builder)["Letters | No Y"])["visualContainers"][CHART]["singleVisual"]
    assert chart["projections"]["Y"] == []
    assert [(s["index"], s["length"]) for s in chart["parameters"]["Y"]] == [(0, 0)]


# -- legacy layout ---------------------------------------------------------------
LEGACY_ROWS = [{"table": "_Campaigns", "column": "Campaign Name", "label": "Campaign"},
               {"table": "_Campaigns", "column": "Channel", "label": "Channel"}]


def _legacy_entry(tmp_path: Path, rows=LEGACY_ROWS, **extra) -> Path:
    return _write_config(tmp_path, [{"displayName": "Spend | Legacy", "analysis_category": "Spend",
                                     "pickers": {"x_selector_1": MEASURES, "y_selector_2": rows},
                                     **extra}])


def test_legacy_layout_does_not_mirror_rows(builder, tmp_path):
    _set_wells(builder, 'row_dropdowns = ["y_selector_3", "y_selector_4", "y_selector_5", "y_selector_6"]',
               "row_dropdowns = []")
    result = _build(builder, _legacy_entry(tmp_path), "--base", BASE_ID, "--group", GROUP,
                    "--legacy-layout")
    assert result.exit_code == 0, result.output


def test_legacy_layout_empties_a_dropdown_the_entry_leaves_out(builder, tmp_path):
    _with_values_slicers(builder, keys={"y_values_slicer_3": VALUES_3}, capture=(VALUES_3,))
    result = _build(builder, _legacy_entry(tmp_path), "--base", BASE_ID, "--group", GROUP,
                    "--legacy-layout")
    assert result.exit_code == 0, result.output
    sec = _section(_by_display(builder)["Spend | Legacy"])
    assert _general_filter(sec["visualContainers"][PICKERS["y_selector_3"]]["singleVisual"])["Where"] == []
    single = sec["visualContainers"][VALUES_3]["singleVisual"]
    assert _general_filter(single)["Where"] == []
    assert single["projections"] == _values_slicer("_Issues", "Issue Topic")["singleVisual"]["projections"]


def test_legacy_layout_moves_a_matrix_captured_under_a_stale_id(builder, tmp_path):
    stale = "0123456789abcdef0123"

    def move(data):
        containers = _section(data)["visualContainers"]
        containers[stale] = containers.pop(MATRIX)
    _edit_base(builder, move)
    result = _build(builder, _legacy_entry(tmp_path), "--base", BASE_ID, "--group", GROUP,
                    "--legacy-layout")
    assert result.exit_code == 0, result.output
    containers = _section(_by_display(builder)["Spend | Legacy"])["visualContainers"]
    assert stale not in containers
    assert [p["Measure"]["Property"] for p in containers[MATRIX]["singleVisual"]["projections"]["Values"]] \
        == ["Cost", "Clicks", "CPC"]
    assert stale in result.output and MATRIX in result.output


def test_legacy_layout_reads_the_category_filter_from_the_named_map(builder, tmp_path):
    def to_named(data):
        filters = _section(data)["filters"]
        cat = next(f for f in filters["byExpr"] if f["name"] == "f_category")
        filters["byExpr"].remove(cat)
        filters["byName"] = {"f_category": cat}
    _edit_base(builder, to_named)
    assert _build(builder, _legacy_entry(tmp_path), "--base", BASE_ID, "--group", GROUP,
                  "--legacy-layout").exit_code == 0
    cat = _section(_by_display(builder)["Spend | Legacy"])["filters"]["byName"]["f_category"]
    assert cat["filter"]["Where"][0]["Condition"]["In"]["Values"] == [[{"Literal": {"Value": "'Spend'"}}]]


def test_legacy_layout_without_a_category_filter_skips_it(builder, tmp_path):
    def drop(data):
        filters = _section(data)["filters"]
        filters["byExpr"] = [f for f in filters["byExpr"] if f["name"] != "f_category"]
    _edit_base(builder, drop)
    result = _build(builder, _legacy_entry(tmp_path), "--base", BASE_ID, "--group", GROUP,
                    "--legacy-layout")
    assert result.exit_code == 0, result.output


def test_legacy_layout_scopes_the_bookmark_to_the_matrix(builder, tmp_path):
    assert _build(builder, _legacy_entry(tmp_path), "--base", BASE_ID, "--group", GROUP,
                  "--legacy-layout").exit_code == 0
    assert _by_display(builder)["Spend | Legacy"]["options"]["targetVisualNames"] == [MATRIX]


def test_legacy_layout_keeps_explicit_target_visuals(builder, tmp_path):
    assert _build(builder, _legacy_entry(tmp_path, target_visuals=[CHART]), "--base", BASE_ID,
                  "--group", GROUP, "--legacy-layout").exit_code == 0
    assert _by_display(builder)["Spend | Legacy"]["options"]["targetVisualNames"] == [CHART]


def test_legacy_layout_points_the_first_matrix_filter_at_the_first_measure(builder, tmp_path):
    def add_filters(data):
        _section(data)["visualContainers"][MATRIX]["filters"] = {"byExpr": [
            {"name": "mf", "type": "Advanced", "expression": _column("_Legacy", "Legacy Row"),
             "howCreated": 1},
            {"name": "mf2", "expression": _column("_Legacy", "Legacy Row")}]}
    _edit_base(builder, add_filters)
    assert _build(builder, _legacy_entry(tmp_path), "--base", BASE_ID, "--group", GROUP,
                  "--legacy-layout").exit_code == 0
    flts = _section(_by_display(builder)["Spend | Legacy"])["visualContainers"][MATRIX]["filters"]["byExpr"]
    assert flts[0] == {"name": "mf", "type": "Advanced", "howCreated": 1, "expression": {"Measure": {
        "Expression": {"SourceRef": {"Entity": "Spend Measures"}}, "Property": "Cost"}}}
    assert flts[1]["expression"] == _column("_Legacy", "Legacy Row")


def test_legacy_layout_edits_the_matrix_capture_in_place(builder, tmp_path):
    second_sort = {"Direction": 2, "Expression": _column("_Legacy", "Legacy Row")}

    def enrich(data):
        mx = _section(data)["visualContainers"][MATRIX]["singleVisual"]
        mx["orderBy"] = [{"Direction": 1, "Expression": _column("_Legacy", "Legacy Row")}, second_sort]
        mx["parameters"]["Values"][0]["sortDirection"] = 1
        mx["projections"]["Columns"] = [_column("_Legacy", "Legacy Row")]
    _edit_base(builder, enrich)
    base_mx = _section(load(_bookmarks_dir(builder) / f"{BASE_ID}.bookmark.json"))[
        "visualContainers"][MATRIX]["singleVisual"]
    assert _build(builder, _legacy_entry(tmp_path), "--base", BASE_ID, "--group", GROUP,
                  "--legacy-layout").exit_code == 0
    mx = _matrix(builder, "Spend | Legacy")
    assert mx["orderBy"][0]["Direction"] == 1
    assert mx["orderBy"][0]["Expression"]["Measure"]["Property"] == "Cost"
    assert mx["orderBy"][1] == second_sort
    slot = mx["parameters"]["Values"][0]
    assert (slot["index"], slot["length"], slot["sortDirection"]) == (0, 3, 1)
    assert mx["projections"]["Columns"] == base_mx["projections"]["Columns"]
    for key in ("display", "expansionStates", "prototypeQuery"):
        assert mx[key] == base_mx[key], key
    assert len(mx["activeProjections"]["Rows"]) == 2
    assert mx["activeProjections"]["Values"] == base_mx["activeProjections"]["Values"]


def test_legacy_layout_adds_a_descending_sort_only_when_none_exists(builder, tmp_path):
    def drop(data):
        _section(data)["visualContainers"][MATRIX]["singleVisual"].pop("orderBy", None)
    _edit_base(builder, drop)
    assert _build(builder, _legacy_entry(tmp_path), "--base", BASE_ID, "--group", GROUP,
                  "--legacy-layout").exit_code == 0
    order = _matrix(builder, "Spend | Legacy")["orderBy"]
    assert len(order) == 1 and order[0]["Direction"] == 2


# -- output and entries ------------------------------------------------------------
def test_bookmark_files_keep_non_ascii_text_as_utf8(builder, tmp_path):
    pick = {"table": "Newsletter Measures", "column": "Ανοίγματα #", "label": "Ανοίγματα"}
    cfg = _write_config(tmp_path, [{"displayName": "Lettres | Été", "pickers": {"x_selector_2": [pick]}}])
    assert _build(builder, cfg, "--base", BASE_ID, "--group", GROUP).exit_code == 0
    name = _by_display(builder)["Lettres | Été"]["name"]
    raw = (_bookmarks_dir(builder) / f"{name}.bookmark.json").read_bytes()
    assert "Été".encode() in raw and "Ανοίγματα".encode() in raw
    assert b"\\u" not in raw


def test_default_calendar_hierarchy_and_alias(builder, tmp_path):
    from pbi_plot_styler.bookmark_builder import BuilderSettings
    assert BuilderSettings().calendar_hierarchy == "Calendar Hierarchy"
    toml = builder / "builder.toml"
    toml.write_text(toml.read_text(encoding="utf-8").replace(
        'calendar_hierarchy = "Date Hierarchy"\n', ""), encoding="utf-8")
    cfg = _write_config(tmp_path, [{"displayName": "Letters | Year", "date_filter": "this_year"}])
    assert _build(builder, cfg, "--base", BASE_ID, "--group", GROUP).exit_code == 0
    date = next(f for f in _section(_by_display(builder)["Letters | Year"])["filters"]["byExpr"]
                if f["name"] == "f_date")
    assert date["filter"]["From"] == [{"Name": "_", "Entity": "__Calendar", "Type": 0}]
    hier = date["filter"]["Where"][0]["Condition"]["Comparison"]["Left"]["HierarchyLevel"]["Expression"]
    assert hier == {"Hierarchy": {"Expression": {"SourceRef": {"Source": "_"}},
                                  "Hierarchy": "Calendar Hierarchy"}}


def test_an_entry_can_name_its_own_base(builder, tmp_path):
    other = "c0ffee00c0ffee00c0ff"
    data = load(_bookmarks_dir(builder) / f"{BASE_ID}.bookmark.json")
    data["name"], data["displayName"] = other, "Base | Other"
    _section(data)["visualContainers"]["aabeebfe4cbc288aa93c"]["singleVisual"].pop("display")
    dump(_bookmarks_dir(builder) / f"{other}.bookmark.json", data)
    cfg = _write_config(tmp_path, [{"displayName": "Letters | From base"},
                                   {"displayName": "Letters | From other", "base": other}])
    assert _build(builder, cfg, "--base", BASE_ID, "--group", GROUP).exit_code == 0
    built = _by_display(builder)
    card = lambda d: _section(built[d])["visualContainers"]["aabeebfe4cbc288aa93c"]["singleVisual"]  # noqa: E731
    assert card("Letters | From base")["display"] == {"mode": "hidden"}
    assert "display" not in card("Letters | From other")


def test_clear_filters_applies_to_new_bookmarks(builder, tmp_path):
    cfg = _write_config(tmp_path, [{"displayName": "Letters | Cleared", "clear_filters": ["f_legacy"]}])
    assert _build(builder, cfg, "--base", BASE_ID, "--group", GROUP).exit_code == 0
    bm = _by_display(builder)["Letters | Cleared"]
    for holder in (bm["explorationState"], _section(bm)):
        flt = next(f for f in holder["filters"]["byExpr"] if f["name"] == "f_legacy")
        assert "filter" not in flt


def test_rerender_never_reregisters_a_kept_bookmark(builder, tmp_path):
    cfg = _write_config(tmp_path, [{"displayName": "Letters | Grouped"}])
    assert _build(builder, cfg, "--base", BASE_ID, "--group", GROUP).exit_code == 0
    index = _bookmarks_dir(builder) / "bookmarks.json"
    before = index.read_bytes()
    result = _build(builder, cfg, "--base", BASE_ID, "--keep-ids")
    assert result.exit_code == 0, result.output
    assert index.read_bytes() == before


def test_rerender_output_says_kept_or_new(builder, tmp_path):
    cfg = _write_config(tmp_path, [{"displayName": "Letters | Old"}])
    assert _build(builder, cfg, "--base", BASE_ID, "--group", GROUP).exit_code == 0
    cfg = _write_config(tmp_path, [{"displayName": "Letters | Old"}, {"displayName": "Letters | New"}])
    result = _build(builder, cfg, "--base", BASE_ID, "--group", GROUP, "--keep-ids")
    assert result.exit_code == 0, result.output
    lines = [line for line in result.output.splitlines() if "bookmark.json" in line]
    assert "(kept id): Letters | Old" in lines[0]
    assert "(new id): Letters | New" in lines[1]


def test_rerender_with_two_bookmarks_of_one_display_name_is_an_error(builder, tmp_path):
    cfg = _write_config(tmp_path, [{"displayName": "Letters | Twin"}, {"displayName": "Letters | Twin"}])
    assert _build(builder, cfg, "--base", BASE_ID, "--group", GROUP).exit_code == 0
    names = sorted(bm["name"] for f in _bookmarks_dir(builder).glob("*.bookmark.json")
                   if (bm := load(f))["displayName"] == "Letters | Twin")
    before = _files_snapshot(builder)
    result = _build(builder, _write_config(tmp_path, [{"displayName": "Letters | Twin"}]),
                    "--base", BASE_ID, "--keep-ids")
    assert result.exit_code == 2
    assert all(n in result.output for n in names)
    assert _files_snapshot(builder) == before


def test_empty_picks_keep_the_slicer_shape(builder, tmp_path):
    cfg = _write_config(tmp_path, [{"displayName": "Letters | Empty pick", "pickers": {"x_selector_2": []}}])
    assert _build(builder, cfg, "--base", BASE_ID, "--group", GROUP).exit_code == 0
    single = _section(_by_display(builder)["Letters | Empty pick"])["visualContainers"][
        PICKERS["x_selector_2"]]["singleVisual"]
    where = _general_filter(single)["Where"]
    assert where[0]["Condition"]["In"]["Values"] == []
    assert single["cachedFilterDisplayItems"] == []


def test_legacy_empty_picks_drop_conditions_and_keep_an_empty_cache(builder, tmp_path):
    assert _build(builder, _legacy_entry(tmp_path), "--base", BASE_ID, "--group", GROUP,
                  "--legacy-layout").exit_code == 0
    single = _section(_by_display(builder)["Spend | Legacy"])["visualContainers"][
        PICKERS["x_ps1"]]["singleVisual"]
    assert _general_filter(single)["Where"] == []
    assert single["cachedFilterDisplayItems"] == []


@pytest.mark.parametrize("sort,direction,kind,prop", [
    ({"table": "Newsletter Measures", "column": "Letters Sent #"}, 2, "Measure", "Letters Sent #"),
    ({"table": "Newsletter Measures", "column": "Letters Sent #", "direction": "1"}, 1, "Measure",
     "Letters Sent #"),
    ({"table": "_Accounts", "column": "Account Name", "direction": 1, "kind": "column"}, 1, "Column",
     "Account Name"),
    ({"measure": {"table": "Newsletter Measures", "column": "X"}, "direction": "descending"}, 2, "Measure", "X"),
])
def test_matrix_sort_flat_form_and_direction(builder, tmp_path, sort, direction, kind, prop):
    cfg = _write_config(tmp_path, [{"displayName": "Letters | Sort", "matrix_sort": sort}])
    result = _build(builder, cfg, "--base", BASE_ID, "--group", GROUP)
    assert result.exit_code == 0, result.output
    order = _matrix(builder, "Letters | Sort")["orderBy"]
    assert order[0]["Direction"] == direction
    assert order[0]["Expression"][kind]["Property"] == prop


@pytest.mark.parametrize("extra", [
    {"analysis_category": None}, {"analysis_category": ""}, {"analysis_category": []},
    {"drill_level": None}, {"drill_level": ""}, {"date_filter": None},
])
def test_null_category_drill_and_date_leave_the_base(builder, tmp_path, extra):
    cfg = _write_config(tmp_path, [{"displayName": "Letters | Nulls", **extra}])
    result = _build(builder, cfg, "--base", BASE_ID, "--group", GROUP)
    assert result.exit_code == 0, result.output
    sec = _section(_by_display(builder)["Letters | Nulls"])
    base = _section(load(_bookmarks_dir(builder) / f"{BASE_ID}.bookmark.json"))
    assert sec["filters"] == base["filters"]
    assert sec["visualContainers"][CHART]["singleVisual"]["activeProjections"] == \
        base["visualContainers"][CHART]["singleVisual"]["activeProjections"]


def test_an_unknown_date_value_is_an_error(builder, tmp_path):
    cfg = _write_config(tmp_path, [{"displayName": "Letters | Last year", "date_filter": "last_year"}])
    assert _build(builder, cfg, "--base", BASE_ID, "--group", GROUP).exit_code == 2


def test_unknown_entry_keys_are_ignored(builder, tmp_path):
    cfg = _write_config(tmp_path, [{"displayName": "Letters | Extra", "notes": "kept for people"}])
    result = _build(builder, cfg, "--base", BASE_ID, "--group", GROUP)
    assert result.exit_code == 0, result.output
    assert "notes" not in _by_display(builder)["Letters | Extra"]


def test_a_missing_chart_capture_is_an_error(builder, tmp_path):
    _edit_base(builder, lambda d: _section(d)["visualContainers"].pop(CHART))
    pick = {"table": "Newsletter Measures", "column": "A", "label": "A"}
    cfg = _write_config(tmp_path, [{"displayName": "Letters | No chart", "pickers": {"x_ps1": [pick]}}])
    before = _files_snapshot(builder)
    result = _build(builder, cfg, "--base", BASE_ID, "--group", GROUP)
    assert result.exit_code == 2 and "chart" in result.output
    assert _files_snapshot(builder) == before


def test_a_repeated_pick_in_a_chart_well_is_an_error(builder, tmp_path):
    _set_wells(builder, 'chart_y = ["x_ps1"]', 'chart_y = ["x_ps1", "x_selector_1"]')
    pick = {"table": "Newsletter Measures", "column": "A", "label": "A"}
    cfg = _write_config(tmp_path, [{"displayName": "Letters | Twice", "pickers": {
        "x_ps1": [pick], "x_selector_1": [pick]}}])
    result = _build(builder, cfg, "--base", BASE_ID, "--group", GROUP)
    assert result.exit_code == 2 and "picked twice" in result.output


def test_a_failed_build_exits_2_and_writes_nothing(builder, tmp_path):
    cfg = _write_config(tmp_path, [{"displayName": "Letters | Fine"},
                                   {"displayName": "Letters | Bad", "group": "no-such-group"}])
    before = _files_snapshot(builder)
    assert _build(builder, cfg, "--base", BASE_ID, "--group", GROUP).exit_code == 2
    assert _files_snapshot(builder) == before

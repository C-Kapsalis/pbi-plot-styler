"""F-measure-color-sync: ``colors sync`` / ``colors reset`` from a palette measure.

Fixture ``fixtures/color-sync``: palette
measure ``'w-Colors'[c-Measure Color]`` with offset 0, modulus 3, base 1 and
slots 1..3; picker ``x-Selector 1`` rows Revenue (order 1) and Orders (order 2),
so Revenue gets slot 2 (``#222222``) and Orders slot 3 (``#333333``).
Exit codes: 0 written or nothing to do, 1 a dry run found changes, 2 invalid
input.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from cli_helpers import copy_fixture, load, run

PAGE = "aa11bb22cc33dd44ee55"
# 0: done, or nothing to do; 1: a dry run found changes to make; 2: usage error
EXIT_CHANGES, EXIT_NONE, EXIT_PENDING, EXIT_INVALID = 0, 0, 1, 2


@pytest.fixture
def shop(tmp_path: Path) -> Path:
    return copy_fixture("color-sync", tmp_path)


def _args(shop: Path) -> list:
    return ["--report", shop / "Shop.Report", "--model", shop / "Shop.SemanticModel"]


def _visual(shop: Path, vid: str) -> dict:
    return load(shop / "Shop.Report" / "definition" / "pages" / PAGE / "visuals" / vid / "visual.json")


def _entry(entries: list, key: str) -> dict | None:
    for e in entries:
        if e.get("selector", {}).get("metadata") == key:
            return e
    return None


def _fill(entry: dict) -> dict:
    return entry["properties"]["fill"]["solid"]["color"]["expr"]


def _snapshot(shop: Path) -> dict[str, bytes]:
    return {str(p): p.read_bytes() for p in sorted(shop.rglob("*")) if p.is_file()}


def test_dry_run_reports_changes_and_writes_nothing(shop):
    before = _snapshot(shop)
    result = run("colors", "sync", *_args(shop))
    assert result.exit_code == EXIT_PENDING, result.output
    assert _snapshot(shop) == before


def test_a_dry_run_with_nothing_to_do_exits_0(shop):
    assert run("colors", "sync", *_args(shop), "--apply").exit_code == EXIT_CHANGES
    result = run("colors", "sync", *_args(shop))
    assert result.exit_code == EXIT_NONE, result.output
    assert "would write 0 file(s): 0 colour entry/entries rewritten, 0 added" \
        in result.output


def test_sync_stamps_bar_fill_from_palette_slot(shop):
    result = run("colors", "sync", *_args(shop), "--apply")
    assert result.exit_code == EXIT_CHANGES, result.output
    data_point = _visual(shop, "combo01")["visual"]["objects"]["dataPoint"]
    assert _fill(_entry(data_point, "Sales Measures.Revenue")) == {"Literal": {"Value": "'#222222'"}}
    # Orders is needed through the multi-series bookmark naming combo01
    assert _fill(_entry(data_point, "Sales Measures.Orders")) == {"Literal": {"Value": "'#333333'"}}


def test_y2_line_entries_are_never_touched(shop):
    before = _entry(_visual(shop, "combo01")["visual"]["objects"]["dataPoint"], "Sales Measures.Basket Size")
    assert run("colors", "sync", *_args(shop), "--apply").exit_code == EXIT_CHANGES
    after = _entry(_visual(shop, "combo01")["visual"]["objects"]["dataPoint"], "Sales Measures.Basket Size")
    assert after == before


def _project_on_matrix(shop: Path, *measures: str) -> None:
    """Add measure projections to matrix01's Values, next to the picker column."""
    path = shop / "Shop.Report" / "definition" / "pages" / PAGE / "visuals" / "matrix01" / "visual.json"
    data = load(path)
    values = data["visual"]["query"]["queryState"]["Values"]["projections"]
    for m in measures:
        values.append({"field": {"Measure": {"Expression": {"SourceRef": {"Entity": "Sales Measures"}},
                                             "Property": m}}, "queryRef": f"Sales Measures.{m}"})
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def test_matrix_columns_get_font_colour_and_style_flags(shop):
    _project_on_matrix(shop, "Revenue", "Orders")
    assert run("colors", "sync", *_args(shop), "--apply").exit_code == EXIT_CHANGES
    formatting = _visual(shop, "matrix01")["visual"]["objects"]["columnFormatting"]
    revenue = _entry(formatting, "Sales Measures.Revenue")
    orders = _entry(formatting, "Sales Measures.Orders")
    assert revenue["properties"]["fontColor"]["solid"]["color"]["expr"] == {"Literal": {"Value": "'#222222'"}}
    assert orders["properties"]["fontColor"]["solid"]["color"]["expr"] == {"Literal": {"Value": "'#333333'"}}
    for entry in (revenue, orders):
        for flag in ("styleValues", "styleHeader", "styleTotal"):
            assert entry["properties"][flag] == {"expr": {"Literal": {"Value": "true"}}}, flag


def _set_matrix_formatting(shop: Path, entries: list) -> None:
    path = shop / "Shop.Report" / "definition" / "pages" / PAGE / "visuals" / "matrix01" / "visual.json"
    data = load(path)
    data["visual"]["objects"] = {"columnFormatting": entries}
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _font(colour: str) -> dict:
    return {"solid": {"color": {"expr": {"Literal": {"Value": f"'{colour}'"}}}}}


def test_a_picker_bound_matrix_colours_only_the_measures_it_projects(shop):
    # the Values well holds only the picker column; the field parameter adds no measure
    _set_matrix_formatting(shop, [{"selector": {"metadata": "Sales Measures.Orders"},
                                   "properties": {"fontColor": _font("#123456")}}])
    assert run("colors", "sync", *_args(shop), "--apply").exit_code == EXIT_CHANGES
    formatting = _visual(shop, "matrix01")["visual"]["objects"]["columnFormatting"]
    assert [e["selector"]["metadata"] for e in formatting] == ["Sales Measures.Orders"]
    props = formatting[0]["properties"]
    assert props["fontColor"]["solid"]["color"]["expr"] == {"Literal": {"Value": "'#000000'"}}
    assert props["styleValues"] == {"expr": {"Literal": {"Value": "true"}}}


def test_second_sync_changes_nothing(shop):
    assert run("colors", "sync", *_args(shop), "--apply").exit_code == EXIT_CHANGES
    before = _snapshot(shop)
    assert run("colors", "sync", *_args(shop), "--apply").exit_code == EXIT_NONE
    assert _snapshot(shop) == before


def test_reset_reverts_palette_fill_to_theme_colour(shop):
    _project_on_matrix(shop, "Revenue")
    assert run("colors", "sync", *_args(shop), "--apply").exit_code == EXIT_CHANGES
    result = run("colors", "reset", *_args(shop), "--apply")
    assert result.exit_code == EXIT_CHANGES, result.output
    data_point = _visual(shop, "combo01")["visual"]["objects"]["dataPoint"]
    assert _fill(_entry(data_point, "Sales Measures.Revenue")) == {"ThemeDataColor": {"ColorId": 9, "Percent": 0}}
    # matrix entries lose the owned properties and are dropped when empty
    formatting = _visual(shop, "matrix01")["visual"]["objects"].get("columnFormatting") or []
    assert _entry(formatting, "Sales Measures.Revenue") is None


def test_palette_with_fewer_slots_than_modulus_is_invalid(shop):
    palette = shop / "Shop.SemanticModel" / "definition" / "tables" / "w-Colors.tmdl"
    palette.write_text(palette.read_text(encoding="utf-8").replace(', 3, "#333333"', ""), encoding="utf-8")
    before = _snapshot(shop)
    result = run("colors", "sync", *_args(shop), "--apply")
    assert result.exit_code == EXIT_INVALID, result.output
    assert _snapshot(shop) == before


def test_unresolvable_bare_reference_is_invalid(shop):
    picker = shop / "Shop.SemanticModel" / "definition" / "tables" / "x-Selector 1.tmdl"
    picker.write_text(picker.read_text(encoding="utf-8").replace(
        "'Sales Measures'[Orders]", "[No Such Measure]"), encoding="utf-8")
    assert run("colors", "sync", *_args(shop), "--apply").exit_code == EXIT_INVALID


def test_missing_palette_measure_is_invalid(shop):
    assert run("colors", "sync", *_args(shop), "--measure", "c-Nope").exit_code == EXIT_INVALID


def _set_slot_expression(shop: Path, expression: str) -> None:
    palette = shop / "Shop.SemanticModel" / "definition" / "tables" / "w-Colors.tmdl"
    palette.write_text(palette.read_text(encoding="utf-8").replace(
        "MOD ( _order + 0, 3 )", expression), encoding="utf-8")


def test_a_negative_offset_shifts_every_colour_by_one_slot(shop):
    _set_slot_expression(shop, "MOD ( _order - 1, 3 )")
    assert run("colors", "sync", *_args(shop), "--apply").exit_code == EXIT_CHANGES
    data_point = _visual(shop, "combo01")["visual"]["objects"]["dataPoint"]
    assert _fill(_entry(data_point, "Sales Measures.Revenue")) == {"Literal": {"Value": "'#111111'"}}
    assert _fill(_entry(data_point, "Sales Measures.Orders")) == {"Literal": {"Value": "'#222222'"}}


def test_a_positive_offset_is_read_too(shop):
    _set_slot_expression(shop, "MOD ( _order + 2, 3 )")
    assert run("colors", "sync", *_args(shop), "--apply").exit_code == EXIT_CHANGES
    data_point = _visual(shop, "combo01")["visual"]["objects"]["dataPoint"]
    assert _fill(_entry(data_point, "Sales Measures.Revenue")) == {"Literal": {"Value": "'#111111'"}}


def test_a_slot_expression_it_cannot_read_is_rejected(shop):
    _set_slot_expression(shop, "MOD ( _order * 2, 3 )")
    before = _snapshot(shop)
    result = run("colors", "sync", *_args(shop), "--apply")
    assert result.exit_code == EXIT_INVALID, result.output
    assert "offset" in result.output
    assert _snapshot(shop) == before


# -- bookmark formatting overrides (objects.merge) ----------------------------------
BOOKMARK = "b0c0d0e0f0a0b0c0d0e0"


def _bookmark_path(shop: Path) -> Path:
    return shop / "Shop.Report" / "definition" / "bookmarks" / f"{BOOKMARK}.bookmark.json"


def _merge_entry(metadata: str, colour: str) -> dict:
    return {"selector": {"metadata": metadata},
            "properties": {"fill": {"solid": {"color": {"expr": {"Literal": {"Value": f"'{colour}'"}}}}}}}


def _with_overrides(shop: Path) -> None:
    path = _bookmark_path(shop)
    data = load(path)
    section = next(iter(data["explorationState"]["sections"].values()))
    single = section["visualContainers"]["combo01"]["singleVisual"]
    single["objects"] = {"merge": {"dataPoint": [
        _merge_entry("Sales Measures.Revenue", "#000000"),
        _merge_entry("Sales Measures.Basket Size", "#abcdef"),
    ]}}
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _overrides(shop: Path) -> dict[str, dict]:
    data = load(_bookmark_path(shop))
    section = next(iter(data["explorationState"]["sections"].values()))
    merge = section["visualContainers"]["combo01"]["singleVisual"]["objects"]["merge"]
    return {e["selector"]["metadata"]: e for e in merge["dataPoint"]}


def test_existing_bookmark_overrides_are_completed_and_recoloured(shop):
    _with_overrides(shop)
    result = run("colors", "sync", *_args(shop), "--apply")
    assert result.exit_code == EXIT_CHANGES, result.output
    assert "overrides" in result.output
    entries = _overrides(shop)
    assert _fill(entries["Sales Measures.Revenue"]) == {"Literal": {"Value": "'#222222'"}}
    # unregistered entries keep their colour; the missing needed measure is added
    assert _fill(entries["Sales Measures.Basket Size"]) == {"Literal": {"Value": "'#abcdef'"}}
    assert _fill(entries["Sales Measures.Orders"]) == {"Literal": {"Value": "'#333333'"}}
    before = _snapshot(shop)
    assert run("colors", "sync", *_args(shop), "--apply").exit_code == EXIT_NONE
    assert _snapshot(shop) == before


def test_a_dry_run_leaves_bookmark_overrides_alone(shop):
    _with_overrides(shop)
    before = _snapshot(shop)
    result = run("colors", "sync", *_args(shop))
    assert result.exit_code == EXIT_PENDING, result.output
    assert "overrides" in result.output
    assert _snapshot(shop) == before


def _bookmark_section(data: dict) -> dict:
    return next(iter(data["explorationState"]["sections"].values()))


def _edit_bookmark(shop: Path, mutate) -> None:
    path = _bookmark_path(shop)
    data = load(path)
    mutate(_bookmark_section(data))
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _matrix_capture(entries: list | None, *, wrapped: bool = True) -> dict:
    single: dict = {"visualType": "pivotTable"}
    if entries is not None:
        single["objects"] = {"merge": {"columnFormatting": entries}} if wrapped \
            else {"columnFormatting": entries}
    return {"singleVisual": single}


def test_a_container_without_the_array_stays_without_one(shop):
    assert run("colors", "sync", *_args(shop), "--apply").exit_code == EXIT_CHANGES
    single = _bookmark_section(load(_bookmark_path(shop)))["visualContainers"]["combo01"]["singleVisual"]
    assert "objects" not in single


def test_an_unwrapped_override_is_recoloured(shop):
    def unwrapped(section):
        section["visualContainers"]["combo01"]["singleVisual"]["objects"] = {"dataPoint": [
            _merge_entry("Sales Measures.Revenue", "#000000")]}
    _edit_bookmark(shop, unwrapped)
    assert run("colors", "sync", *_args(shop), "--apply").exit_code == EXIT_CHANGES
    objects = _bookmark_section(load(_bookmark_path(shop)))["visualContainers"]["combo01"][
        "singleVisual"]["objects"]
    fills = {e["selector"]["metadata"]: _fill(e) for e in objects["dataPoint"]}
    assert fills == {"Sales Measures.Revenue": {"Literal": {"Value": "'#222222'"}},
                     "Sales Measures.Orders": {"Literal": {"Value": "'#333333'"}}}


def test_a_matrix_override_blackens_registered_measures_it_does_not_need(shop):
    _project_on_matrix(shop, "Revenue")
    _edit_bookmark(shop, lambda sec: sec["visualContainers"].update({"matrix01": _matrix_capture([
        {"selector": {"metadata": "Sales Measures.Orders"}, "properties": {"fontColor": _font("#123456")}}])}))
    assert run("colors", "sync", *_args(shop), "--apply").exit_code == EXIT_CHANGES
    merge = _bookmark_section(load(_bookmark_path(shop)))["visualContainers"]["matrix01"][
        "singleVisual"]["objects"]["merge"]["columnFormatting"]
    by_key = {e["selector"]["metadata"]: e["properties"] for e in merge}
    assert by_key["Sales Measures.Orders"]["fontColor"] == _font("#000000")
    assert by_key["Sales Measures.Revenue"]["fontColor"] == _font("#222222")


def test_overrides_are_matched_on_page_and_visual_id(shop):
    path = _bookmark_path(shop)
    data = load(path)
    sec = _bookmark_section(data)
    data["explorationState"]["sections"] = {"other-page": sec}
    sec["visualContainers"]["combo01"]["singleVisual"]["objects"] = {"merge": {"dataPoint": [
        _merge_entry("Sales Measures.Revenue", "#000000")]}}
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    run("colors", "sync", *_args(shop), "--apply")
    merge = _bookmark_section(load(path))["visualContainers"]["combo01"]["singleVisual"]["objects"]["merge"]
    assert [_fill(e) for e in merge["dataPoint"]] == [{"Literal": {"Value": "'#000000'"}}]


def test_reset_reverts_bookmark_overrides(shop):
    _with_overrides(shop)
    _project_on_matrix(shop, "Revenue")
    _edit_bookmark(shop, lambda sec: sec["visualContainers"].update({"matrix01": _matrix_capture([
        {"selector": {"metadata": "Sales Measures.Revenue"}, "properties": {"fontColor": _font("#123456")}}])}))
    assert run("colors", "sync", *_args(shop), "--apply").exit_code == EXIT_CHANGES
    result = run("colors", "reset", *_args(shop), "--apply")
    assert result.exit_code == EXIT_CHANGES, result.output
    assert "overrides reverted" in result.output
    section = _bookmark_section(load(_bookmark_path(shop)))
    combo = section["visualContainers"]["combo01"]["singleVisual"]["objects"]["merge"]["dataPoint"]
    fills = {e["selector"]["metadata"]: _fill(e) for e in combo}
    theme = {"ThemeDataColor": {"ColorId": 9, "Percent": 0}}
    assert fills["Sales Measures.Revenue"] == theme and fills["Sales Measures.Orders"] == theme
    assert fills["Sales Measures.Basket Size"] == {"Literal": {"Value": "'#abcdef'"}}
    assert "columnFormatting" not in section["visualContainers"]["matrix01"]["singleVisual"]["objects"]["merge"]
    before = _snapshot(shop)
    again = run("colors", "reset", *_args(shop), "--apply")
    assert again.exit_code == EXIT_NONE and "0 file(s) written" in again.output
    assert _snapshot(shop) == before


def test_sync_keeps_the_palettes_hex_spelling(shop):
    palette = shop / "Shop.SemanticModel" / "definition" / "tables" / "w-Colors.tmdl"
    palette.write_text(palette.read_text(encoding="utf-8").replace(
        '"#222222"', '"#ABCDEF"').replace('"#333333"', '"#FEDCBA"'), encoding="utf-8")
    assert run("colors", "sync", *_args(shop), "--apply").exit_code == EXIT_CHANGES
    data_point = _visual(shop, "combo01")["visual"]["objects"]["dataPoint"]
    assert _fill(_entry(data_point, "Sales Measures.Revenue")) == {"Literal": {"Value": "'#ABCDEF'"}}
    before = _snapshot(shop)
    result = run("colors", "sync", *_args(shop), "--apply")
    assert result.exit_code == EXIT_NONE
    assert "wrote 0 file(s): 0 colour entry/entries rewritten, 0 added" \
        in result.output
    assert _snapshot(shop) == before
    # reset still recognises the colour
    assert run("colors", "reset", *_args(shop), "--apply").exit_code == EXIT_CHANGES
    data_point = _visual(shop, "combo01")["visual"]["objects"]["dataPoint"]
    assert _fill(_entry(data_point, "Sales Measures.Revenue")) == {"ThemeDataColor": {"ColorId": 9, "Percent": 0}}


def _add_visual(shop: Path, vid: str, visual: dict) -> None:
    folder = shop / "Shop.Report" / "definition" / "pages" / PAGE / "visuals" / vid
    folder.mkdir()
    (folder / "visual.json").write_text(json.dumps({"name": vid, "visual": visual}, indent=2) + "\n",
                                        encoding="utf-8")


def _picker_param(role: str) -> dict:
    col = {"Column": {"Expression": {"SourceRef": {"Entity": "x-Selector 1"}}, "Property": "x-Selector 1 Fields"}}
    return {role: {"projections": [{"field": col}], "fieldParameters": [
        {"parameterExpr": col, "index": 0, "length": 1}]}}


def test_only_a_value_role_makes_a_visual_use_the_picker(shop):
    _add_visual(shop, "slicer01", {"visualType": "slicer", "query": {"queryState": _picker_param("Values")}})
    _add_visual(shop, "matrix02", {"visualType": "pivotTable", "query": {"queryState": _picker_param("Rows")}})
    _add_visual(shop, "card01", {"visualType": "card", "query": {"queryState": _picker_param("Values")}})
    result = run("colors", "sync", *_args(shop), "--apply")
    assert "not supported" not in result.output
    assert "matrix02" not in result.output
    assert "objects" not in _visual(shop, "matrix02")["visual"]
    noted = run("colors", "sync", *_args(shop), "--visual-type", "card")
    assert "card01: card uses 'x-Selector 1' but is not supported" in noted.output
    assert "slicer01" not in noted.output


def test_reset_takes_a_visual_type_and_reverts_only_registered_measures(shop):
    _project_on_matrix(shop, "Revenue")
    assert run("colors", "sync", *_args(shop), "--apply").exit_code == EXIT_CHANGES
    combo = shop / "Shop.Report" / "definition" / "pages" / PAGE / "visuals" / "combo01" / "visual.json"
    data = load(combo)
    basket = _entry(data["visual"]["objects"]["dataPoint"], "Sales Measures.Basket Size")
    basket["properties"]["fill"] = _font("#222222")  # a palette colour on an unregistered measure
    combo.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    matrix = shop / "Shop.Report" / "definition" / "pages" / PAGE / "visuals" / "matrix01" / "visual.json"
    mdata = load(matrix)
    rev = _entry(mdata["visual"]["objects"]["columnFormatting"], "Sales Measures.Revenue")
    rev["properties"]["styleTotal"] = {"expr": {"Literal": {"Value": "false"}}}
    matrix.write_text(json.dumps(mdata, indent=2) + "\n", encoding="utf-8")

    assert run("colors", "reset", *_args(shop), "--visual-type", "pivotTable", "--apply").exit_code == 0
    data_point = _visual(shop, "combo01")["visual"]["objects"]["dataPoint"]
    assert _fill(_entry(data_point, "Sales Measures.Revenue")) == {"Literal": {"Value": "'#222222'"}}
    rev = _entry(_visual(shop, "matrix01")["visual"]["objects"]["columnFormatting"], "Sales Measures.Revenue")
    assert rev["properties"] == {"styleTotal": {"expr": {"Literal": {"Value": "false"}}}}

    assert run("colors", "reset", *_args(shop), "--apply").exit_code == 0
    data_point = _visual(shop, "combo01")["visual"]["objects"]["dataPoint"]
    assert _fill(_entry(data_point, "Sales Measures.Basket Size")) == {"Literal": {"Value": "'#222222'"}}


def test_reset_loads_the_picker_registry(shop):
    picker = shop / "Shop.SemanticModel" / "definition" / "tables" / "x-Selector 1.tmdl"
    picker.write_text(picker.read_text(encoding="utf-8").replace(
        "'Sales Measures'[Orders]", "[No Such Measure]"), encoding="utf-8")
    assert run("colors", "reset", *_args(shop)).exit_code == EXIT_INVALID


def test_sync_prints_palette_series_and_counts(shop):
    result = run("colors", "sync", *_args(shop))
    out = result.output
    assert "palette: picker 'x-Selector 1', offset 0, modulus 3, 3 slot(s); 2 registered measure(s)" in out
    assert "bookmark 'Sales | Both' on combo01:" in out
    assert "Y      Sales Measures.Revenue: order 1, colour #222222" in out
    assert "Y      Sales Measures.Orders: order 2, colour #333333" in out
    assert "would write" in out and "0 colour entry/entries rewritten, 2 added" in out


def test_line_series_count_in_collisions_and_a_hint_is_printed(shop):
    def with_line(section):
        single = section["visualContainers"]["combo01"]["singleVisual"]
        single["projections"]["Y2"] = [{"Measure": {"Expression": {"SourceRef": {"Entity": "Sales Measures"}},
                                                    "Property": "Basket Size"}}]
    _edit_bookmark(shop, with_line)
    out = run("colors", "sync", *_args(shop)).output
    assert "Y2     Sales Measures.Basket Size: not registered" in out
    assert "Sales Measures.Basket Size is not a row of 'x-Selector 1'" in out

    palette = shop / "Shop.SemanticModel" / "definition" / "tables" / "w-Colors.tmdl"
    palette.write_text(palette.read_text(encoding="utf-8").replace('"#333333"', '"#222222"'),
                       encoding="utf-8")
    out = run("colors", "sync", *_args(shop)).output
    assert "share colour #222222" in out
    assert "hint: re-space" in out


@pytest.mark.parametrize("vtype", ["columnChart", "barChart"])
def test_plain_column_and_bar_charts_are_coloured(shop, vtype):
    combo = shop / "Shop.Report" / "definition" / "pages" / PAGE / "visuals" / "combo01" / "visual.json"
    data = load(combo)
    data["visual"]["visualType"] = vtype
    combo.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    _edit_bookmark(shop, lambda sec: sec["visualContainers"]["combo01"]["singleVisual"].update(
        {"visualType": vtype}))
    assert run("colors", "sync", *_args(shop), "--apply").exit_code == EXIT_CHANGES
    data_point = _visual(shop, "combo01")["visual"]["objects"]["dataPoint"]
    assert _fill(_entry(data_point, "Sales Measures.Orders")) == {"Literal": {"Value": "'#333333'"}}
    assert run("colors", "reset", *_args(shop), "--apply").exit_code == EXIT_CHANGES
    data_point = _visual(shop, "combo01")["visual"]["objects"]["dataPoint"]
    assert _fill(_entry(data_point, "Sales Measures.Orders")) == {"ThemeDataColor": {"ColorId": 9, "Percent": 0}}

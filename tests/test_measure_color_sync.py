"""F-measure-color-sync: ``colors sync`` / ``colors reset`` from a palette measure.

New tests (no original pytest test). Fixture ``fixtures/color-sync``: palette
measure ``'w-Colors'[c-Measure Color]`` with offset 0, modulus 3, base 1 and
slots 1..3; picker ``x-Selector 1`` rows Revenue (order 1) and Orders (order 2),
so Revenue gets slot 2 (``#222222``) and Orders slot 3 (``#333333``).
Exit codes: 0 changes, 2 no change, 3 invalid input.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ported_helpers import copy_fixture, load, run

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
    assert "0 change(s)" in result.output


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


def test_matrix_columns_get_font_colour_and_style_flags(shop):
    assert run("colors", "sync", *_args(shop), "--apply").exit_code == EXIT_CHANGES
    formatting = _visual(shop, "matrix01")["visual"]["objects"]["columnFormatting"]
    revenue = _entry(formatting, "Sales Measures.Revenue")
    orders = _entry(formatting, "Sales Measures.Orders")
    assert revenue["properties"]["fontColor"]["solid"]["color"]["expr"] == {"Literal": {"Value": "'#222222'"}}
    assert orders["properties"]["fontColor"]["solid"]["color"]["expr"] == {"Literal": {"Value": "'#333333'"}}
    for entry in (revenue, orders):
        for flag in ("styleValues", "styleHeader", "styleTotal"):
            assert entry["properties"][flag] == {"expr": {"Literal": {"Value": "true"}}}, flag


def test_second_sync_changes_nothing(shop):
    assert run("colors", "sync", *_args(shop), "--apply").exit_code == EXIT_CHANGES
    before = _snapshot(shop)
    assert run("colors", "sync", *_args(shop), "--apply").exit_code == EXIT_NONE
    assert _snapshot(shop) == before


def test_reset_reverts_palette_fill_to_theme_colour(shop):
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

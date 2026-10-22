"""The console output of ``colors sync`` and ``colors reset``.

The two commands print the palette header, the multi-series bookmark
listing, the collisions and the unregistered series, and close with the
count of the files they would write.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from cli_helpers import copy_fixture, load, run

EXIT_OK, EXIT_PENDING, EXIT_INVALID = 0, 1, 2


@pytest.fixture
def shop(tmp_path: Path) -> Path:
    return copy_fixture("color-sync", tmp_path)


def _args(shop: Path) -> list:
    return ["--report", shop / "Shop.Report", "--model", shop / "Shop.SemanticModel"]


def _table(shop: Path, name: str) -> Path:
    return shop / "Shop.SemanticModel" / "definition" / "tables" / f"{name}.tmdl"


def _bookmark(shop: Path) -> Path:
    return shop / "Shop.Report" / "definition" / "bookmarks" / \
        "b0c0d0e0f0a0b0c0d0e0.bookmark.json"


def _add_visual(shop: Path, vid: str, visual: dict) -> None:
    folder = shop / "Shop.Report" / "definition" / "pages" / "aa11bb22cc33dd44ee55" \
        / "visuals" / vid
    folder.mkdir(parents=True)
    (folder / "visual.json").write_text(
        json.dumps({"name": vid, "visual": visual}, indent=2) + "\n", encoding="utf-8")


def _picker_param(role: str) -> dict:
    col = {"Column": {"Expression": {"SourceRef": {"Entity": "x-Selector 1"}},
                       "Property": "x-Selector 1 Fields"}}
    return {role: {"projections": [{"field": col}], "fieldParameters": [
        {"parameterExpr": col, "index": 0, "length": 1}]}}


# -- SCX43: the palette header ----------------------------------------------------
def test_sync_prints_the_palette_header(shop):
    out = run("colors", "sync", *_args(shop)).stdout
    assert out.splitlines()[:3] == [
        "palette   : x-Selector 1 -> MOD(order+0, 3)+1 -> 3 slots",
        "registered: 2 measures on the picker",
        "",
    ]


def test_reset_prints_the_palette_header(shop):
    out = run("colors", "reset", *_args(shop)).stdout
    assert out.splitlines()[:3] == [
        "palette   : x-Selector 1 -> MOD(order+0, 3)+1 -> 3 slots",
        "registered: 2 measures on the picker",
        "",
    ]


def test_a_minus_offset_is_written_with_a_minus(shop):
    palette = _table(shop, "w-Colors")
    palette.write_text(palette.read_text(encoding="utf-8").replace(
        "MOD ( _order + 0, 3 )", "MOD ( _order - 1, 3 )"), encoding="utf-8")
    out = run("colors", "sync", *_args(shop)).stdout
    assert "palette   : x-Selector 1 -> MOD(order-1, 3)+1 -> 3 slots" in out


# -- SCX44: the multi-series bookmark listing -------------------------------------
def test_the_listing_names_the_bookmark_and_pads_the_key(shop):
    out = run("colors", "sync", *_args(shop)).stdout
    lines = out.splitlines()
    start = lines.index("  Sales | Both  [combo01]")
    assert lines[start + 1] == (
        f"      bar  {'Sales Measures.Revenue':<60} order={1:<6} #222222")
    assert lines[start + 2] == (
        f"      bar  {'Sales Measures.Orders':<60} order={2:<6} #333333")


def test_a_bookmark_without_a_display_name_uses_its_file_name(shop):
    path = _bookmark(shop)
    data = load(path)
    del data["displayName"]
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    out = run("colors", "sync", *_args(shop)).stdout
    assert "  b0c0d0e0f0a0b0c0d0e0.bookmark  [combo01]" in out


# -- SCX45: the collision block ---------------------------------------------------
def test_two_series_that_share_a_slot_are_reported(shop):
    palette = _table(shop, "w-Colors")
    palette.write_text(palette.read_text(encoding="utf-8").replace(
        '"#333333"', '"#222222"'), encoding="utf-8")
    out = run("colors", "sync", *_args(shop)).stdout
    assert "COLLISIONS -- two series in one bookmark share a slot:" in out
    assert ("  Sales | Both: Sales Measures.Revenue  ==  Sales Measures.Orders  (#222222)"
            in out)
    assert "  Fix by re-spacing the picker Order, never by hand-colouring one of them." in out


# -- SCX46: the unregistered block -------------------------------------------------
def test_an_unregistered_series_is_reported_once(shop):
    data = load(_bookmark(shop))
    section = next(iter(data["explorationState"]["sections"].values()))
    single = section["visualContainers"]["combo01"]["singleVisual"]
    single["projections"]["Y2"] = [{"Measure": {
        "Expression": {"SourceRef": {"Entity": "Sales Measures"}}, "Property": "Basket Size"}}]
    _bookmark(shop).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    out = run("colors", "sync", *_args(shop)).stdout
    assert "NOT REGISTERED on the picker (blank in the matrix too):" in out
    assert "  Sales | Both: Sales Measures.Basket Size" in out
    assert out.count("Sales Measures.Basket Size") == 2  # the listing and the block


# -- SCX47: the unsupported line ----------------------------------------------------
def test_a_visual_that_cannot_carry_a_colour_is_reported(shop):
    _add_visual(shop, "card01", {"visualType": "card",
                                  "query": {"queryState": _picker_param("Values")}})
    out = run("colors", "sync", *_args(shop), "--all-visuals").stdout
    assert ("UNSUPPORTED: card01 (card) uses x-Selector 1; requires a visual "
            "with per-measure colour support") in out


def test_an_out_of_scope_visual_is_not_reported(shop):
    _add_visual(shop, "card01", {"visualType": "card",
                                  "query": {"queryState": _picker_param("Values")}})
    out = run("colors", "sync", *_args(shop), "--visual-type", "card").stdout
    assert "UNSUPPORTED" not in out


# -- SCX48 and SCX49: the closing counts -------------------------------------------
def test_a_dry_run_lists_the_changed_files(shop):
    out = run("colors", "sync", *_args(shop)).stdout
    assert "would write 1 file(s): 0 colour entry/entries rewritten, 2 added" in out
    paths = [ln for ln in out.splitlines()
             if ln.startswith("   ") and not ln.startswith("      ")]
    assert len(paths) == 1
    assert paths[0].endswith("visuals/combo01/visual.json")
    assert out.endswith("(dry run -- pass --apply to write)\n")


def test_reset_counts_the_entries_it_reverts(shop):
    run("colors", "sync", *_args(shop), "--apply")
    out = run("colors", "reset", *_args(shop)).stdout
    assert "would restore " in out
    assert " colour entry/entries in 1 file(s)" in out
    assert out.endswith("(dry run -- pass --apply to write)\n")


# -- SCX50: the lines the original never prints ------------------------------------
def test_no_per_change_lines_are_printed(shop):
    out = run("colors", "sync", *_args(shop)).stdout
    assert "note: " not in out
    assert "dataPoint for" not in out
    assert "columnFormatting for" not in out
    assert "DRY RUN" not in out
    assert "APPLIED" not in out


# -- SCX51: the palette and picker errors -------------------------------------------
def test_the_palette_table_file_is_missing(shop):
    _table(shop, "w-Colors").unlink()
    result = run("colors", "sync", *_args(shop))
    assert result.exit_code == EXIT_INVALID
    assert result.stderr == (
        f"FAIL: {shop / 'Shop.SemanticModel' / 'definition' / 'tables' / 'w-Colors.tmdl'}"
        f" not found\n")


def test_the_palette_measure_is_not_in_the_table(shop):
    result = run("colors", "sync", *_args(shop), "--measure", "c-No Such Colour")
    assert result.exit_code == EXIT_INVALID
    assert result.stderr.startswith("FAIL: [c-No Such Colour] not found in ")


def test_the_palette_measure_has_no_mod_rule(shop):
    palette = _table(shop, "w-Colors")
    palette.write_text(palette.read_text(encoding="utf-8").replace(
        "MOD ( _order + 0, 3 ) + 1", "1"), encoding="utf-8")
    result = run("colors", "sync", *_args(shop))
    assert result.exit_code == EXIT_INVALID
    assert result.stderr == "FAIL: could not read the picker/MOD rule out of [c-Measure Color]\n"


def test_the_palette_lists_the_wrong_number_of_colours(shop):
    palette = _table(shop, "w-Colors")
    palette.write_text(palette.read_text(encoding="utf-8").replace(
        ', 3, "#333333"', ""), encoding="utf-8")
    result = run("colors", "sync", *_args(shop))
    assert result.exit_code == EXIT_INVALID
    assert result.stderr == "FAIL: [c-Measure Color] declares 2 slots for MOD 3\n"


def test_the_picker_table_is_missing(shop):
    picker = _table(shop, "x-Selector 1")
    picker.write_text(picker.read_text(encoding="utf-8").replace(
        "x-Selector 1", "x-Selector 9"), encoding="utf-8")
    _table(shop, "w-Colors").write_text(
        _table(shop, "w-Colors").read_text(encoding="utf-8").replace(
            "'x-Selector 1'", "'x-Selector 1'"), encoding="utf-8")
    result = run("colors", "sync", *_args(shop))
    assert result.exit_code == EXIT_INVALID
    assert result.stderr == (
        f"FAIL: picker table x-Selector 1 not found at "
        f"{shop / 'Shop.SemanticModel' / 'definition' / 'tables' / 'x-Selector 1.tmdl'}\n")


def test_the_picker_has_no_rows(shop):
    picker = _table(shop, "x-Selector 1")
    picker.write_text(picker.read_text(encoding="utf-8").replace(
        '( "Revenue", NAMEOF ( \'Sales Measures\'[Revenue] ), 1 ),\n'
        '				    ( "Orders", NAMEOF ( \'Sales Measures\'[Orders] ), 2 )', ""),
        encoding="utf-8")
    result = run("colors", "sync", *_args(shop))
    assert result.exit_code == EXIT_INVALID
    assert result.stderr == "FAIL: x-Selector 1 parsed to zero entries -- refusing to write\n"


def test_a_bare_nameof_of_an_unknown_measure(shop):
    picker = _table(shop, "x-Selector 1")
    picker.write_text(picker.read_text(encoding="utf-8").replace(
        "NAMEOF ( 'Sales Measures'[Revenue] )", "NAMEOF ( [No Such Measure] )"),
        encoding="utf-8")
    result = run("colors", "sync", *_args(shop))
    assert result.exit_code == EXIT_INVALID
    assert result.stderr == "FAIL: cannot resolve the home table of [No Such Measure]\n"


# -- SCX52: the help texts ------------------------------------------------------------
def test_the_sync_help_carries_the_original_sentences():
    out = " ".join(run("colors", "sync", "--help").output.split())
    assert "Synchronize measure colours across field-parameter columns and tables." in out
    assert "USE THIS WHEN measure colours drifted across visuals or a new measure was" in out
    assert "Read the picker and palette from [c-Measure Color] in w-Colors.tmdl." in out
    assert "Process bookmark formatting overrides as well as base visual formatting." in out
    assert "limit changes to these visual types, e.g. pivotTable" in out
    assert "only report bookmarks pinning at least this many bars" in out
    assert ("include every chart/table, beyond picker matrices and bookmarked "
            "multi-series charts") in out
    assert "ThemeDataColor ColorId used by reset (default: 9)" in out


def test_the_reset_help_carries_the_original_sentence():
    out = " ".join(run("colors", "reset", "--help").output.split())
    assert ("undo this command's literal colours: restore chart series to the report "
            "theme and remove matrix overrides") in out

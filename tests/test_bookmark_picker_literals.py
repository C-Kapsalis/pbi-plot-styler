"""F-bookmark-picker-literals: ``check --rule bookmark-literals`` and T6.

New tests (no original pytest test). Fixture ``fixtures/picker-literals``:
``x-Selector 1`` registers ``NAMEOF([Revenue])`` (home ``Sales Measures``),
``y-Selector 2`` registers ``NAMEOF('Stores'[Region])``. Bookmark
``Sales | Revenue`` captures the x picker selecting Revenue (OK) and the y
picker selecting Region (OK).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ported_helpers import IDS, check_json, copy_fixture, dump, load, of, write_toml

PAGE = "5a5b5c5d5e5f50515253"
BOOKMARK = "c1c1c1c1c1c1c1c1c1c1"


@pytest.fixture
def shop(tmp_path: Path) -> Path:
    return copy_fixture("picker-literals", tmp_path)


def _report(shop: Path) -> Path:
    return shop / "Shop.Report"


def _bm_path(shop: Path) -> Path:
    return _report(shop) / "definition" / "bookmarks" / f"{BOOKMARK}.bookmark.json"


def _set_values(shop: Path, container: str, values: list[str]) -> None:
    path = _bm_path(shop)
    data = load(path)
    sv = data["explorationState"]["sections"][PAGE]["visualContainers"][container]["singleVisual"]
    general = sv["objects"]["merge"]["general"][0]
    cond = general["properties"]["filter"]["filter"]["Where"][0]["Condition"]
    cond["In"]["Values"] = [[{"Literal": {"Value": v}}] for v in values]
    sv.pop("cachedFilterDisplayItems", None)
    dump(path, data)


def _add_card_literal(shop: Path, value: str) -> None:
    path = _bm_path(shop)
    data = load(path)
    data["explorationState"]["sections"][PAGE]["visualContainers"]["card01"] = {"singleVisual": {
        "visualType": "card", "objects": {"general": [{"properties": {"x": {"expr": {"Literal": {"Value": value}}}}}]}}}
    dump(path, data)


def _literal_findings(payload: dict) -> list[dict]:
    return of(payload, "LIT-elsewhere") + of(payload, "LIT-unregistered")


def test_registered_selections_pass(shop):
    payload = check_json(_report(shop), "bookmark-literals")
    assert payload["exit_code"] == 0
    assert _literal_findings(payload) == []


def test_literal_registered_only_in_another_selector(shop):
    _set_values(shop, "xpicker01", ["'''Stores''[Region]'"])
    payload = check_json(_report(shop), "bookmark-literals")
    assert payload["exit_code"] == 1
    found = of(payload, "LIT-elsewhere")
    assert len(found) == 1 and of(payload, "LIT-unregistered") == []
    assert "x-Selector 1" in found[0]["message"]
    assert "'Stores'[Region]" in found[0]["subject"] + found[0]["message"]


def test_literal_registered_nowhere(shop):
    _set_values(shop, "xpicker01", ["'''Stores''[Code]'"])
    payload = check_json(_report(shop), "bookmark-literals")
    assert payload["exit_code"] == 1
    assert len(of(payload, "LIT-unregistered")) == 1
    assert of(payload, "LIT-elsewhere") == []


def test_non_picker_container_needs_registration_anywhere(shop):
    _add_card_literal(shop, "'''Stores''[Region]'")   # registered (in y-Selector 2) -> OK
    assert _literal_findings(check_json(_report(shop), "bookmark-literals")) == []
    _add_card_literal(shop, "'''Stores''[Code]'")     # registered nowhere
    payload = check_json(_report(shop), "bookmark-literals")
    assert [f["id"] for f in _literal_findings(payload)] == [IDS["LIT-unregistered"]]


def test_bare_nameof_resolves_to_home_table(shop):
    # 'Sales Measures'[Orders] is a measure of the home table but not registered
    _set_values(shop, "xpicker01", ["'''Sales Measures''[Revenue]'", "'''Sales Measures''[Orders]'"])
    payload = check_json(_report(shop), "bookmark-literals")
    assert len(of(payload, "LIT-unregistered")) == 1


def test_only_display_names_filter(shop, tmp_path):
    _set_values(shop, "xpicker01", ["'''Stores''[Code]'"])
    only = tmp_path / "only.json"
    only.write_text(json.dumps(["Some | Other"]), encoding="utf-8")
    payload = check_json(_report(shop), "bookmark-literals", "--only-display-names", only)
    assert payload["exit_code"] == 0
    only.write_text(json.dumps(["Sales | Revenue"]), encoding="utf-8")
    payload = check_json(_report(shop), "bookmark-literals", "--only-display-names", only)
    assert payload["exit_code"] == 1


def test_t6_picker_with_empty_selection(shop, tmp_path):
    config = write_toml(tmp_path / "plotstyler.toml", {"answer_bookmarks": {
        "prefixes": ["Sales |"],
        "main_page": PAGE,
        "matrix": "matrix01",
        "slicers": {"x-Selector 1": "xpicker01", "y-Selector 2": "ypicker01"},
    }})
    assert of(check_json(_report(shop), "answer-bookmarks", config=config), "T6") == []
    _set_values(shop, "ypicker01", [])
    payload = check_json(_report(shop), "answer-bookmarks", config=config)
    t6 = of(payload, "T6")
    assert len(t6) == 1
    assert "Sales | Revenue" in t6[0]["subject"]

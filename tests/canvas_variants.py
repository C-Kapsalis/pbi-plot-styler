"""Defect variants of the sample client folder tests/fixtures/universal.

The base sample is compliant with every canvas rule (the combo imposition
skips without a fix). Each variant injects one defect into a copy of the
client folder.

Pure data helpers: no tool imports.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Callable

MAIN = "a0b1c2d3e4f5a6b7c8d9"
OVERVIEW = "f0e1d2c3b4a5968778a9"
REPORT = "-Report.Report"


def _r(client: Path) -> Path:
    return client / REPORT / "definition"


def _v(client: Path, vid: str, page: str = MAIN) -> Path:
    return _r(client) / "pages" / page / "visuals" / vid / "visual.json"


def _load(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def _save(p: Path, d) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, indent=2) + "\n", encoding="utf-8")


def _edit(p: Path, fn: Callable[[dict], None]) -> None:
    d = _load(p)
    fn(d)
    _save(p, d)


# -- rule 1: f-Slicer gate --------------------------------------------------------
def rule1_ungated(client: Path) -> None:
    """A second x-Selector 1 slicer on the canvas page without the gate."""
    d = _load(_v(client, "x_selector_1_slicer"))
    d["name"] = "x_selector_1_ungated"
    d.pop("filterConfig")
    d["position"]["y"] = 80
    _save(_v(client, "x_selector_1_ungated"), d)


# -- rule 3: category filter --------------------------------------------------------
def rule3_missing(client: Path) -> None:
    bm = _r(client) / "bookmarks"
    d = _load(bm / "bA00000000000000000a.bookmark.json")
    d["name"], d["displayName"] = "bC00000000000000000c", "Spend | Clicks"
    d["explorationState"]["sections"][MAIN].pop("filters")
    _save(bm / "bC00000000000000000c.bookmark.json", d)
    _edit(bm / "bookmarks.json", lambda x: x["items"][0]["children"].append("bC00000000000000000c"))


# -- rule 6 / theme -----------------------------------------------------------------
def theme_base_only(client: Path) -> None:
    _edit(_r(client) / "report.json", lambda d: d["themeCollection"].pop("customTheme"))


def theme_empty(client: Path) -> None:
    _edit(_r(client) / "report.json", lambda d: d.update(themeCollection={}))


def theme_hex(client: Path) -> None:
    _edit(_r(client) / "report.json", lambda d: d.update(objects={"outspace": [
        {"properties": {"color": {"solid": {"color": {"expr": {"Literal": {"Value": "'x'"}}}}},
                        "hexColor": "#1A2B3C"}}]}))


# -- rule 8: filter-panel master group ---------------------------------------------
def rule8_renamed(client: Path) -> None:
    """The master group is named g1 / "Filters" (inside hidden "edit canvas")."""
    old = _v(client, "y_filters_group")
    d = _load(old)
    d["name"] = "g1"
    d["visualGroup"]["displayName"] = "Filters"
    shutil.rmtree(old.parent)
    _save(_v(client, "g1"), d)
    for n in range(3, 7):
        _edit(_v(client, f"y_selector_{n}_slicer"), lambda x: x.update(parentGroupName="g1"))
    _edit(_r(client) / "bookmarks" / "bA00000000000000000a.bookmark.json",
          lambda x: x["explorationState"]["sections"][MAIN].update(
              visualContainerGroups={"g1": {"isHidden": False}}))


def rule8_no_groups(client: Path) -> None:
    pages = _r(client) / "pages" / MAIN / "visuals"
    for gid in ("edit_canvas", "y_filters_group", "y1_combo_group"):
        shutil.rmtree(pages / gid)
    for f in pages.glob("*/visual.json"):
        _edit(f, lambda x: x.pop("parentGroupName", None))


# -- visual position ----------------------------------------------------------------
def position_missing_y(client: Path) -> None:
    _edit(_v(client, "card_total", OVERVIEW), lambda d: d["position"].pop("y"))


# -- y-combo naming -----------------------------------------------------------------
def ycombo_bad_name(client: Path) -> None:
    _edit(_v(client, "y1_combo_group"), lambda d: d["visualGroup"].update(displayName="Y1_Combo_Group"))


def ycombo_orphan(client: Path) -> None:
    d = _load(_v(client, "y1_values"))
    d["name"] = "y2_values"
    d.pop("parentGroupName")
    _save(_v(client, "y2_values"), d)


# -- format selector filter ---------------------------------------------------------
def _fmt(client: Path, fn) -> None:
    _edit(_r(client) / "report.json", fn)


def format_no_filter_config(client: Path) -> None:
    _fmt(client, lambda d: d.pop("filterConfig"))


def format_raw(client: Path) -> None:
    def fn(d):
        f = d["filterConfig"]["filters"][0]
        cond = f["filter"]["Where"][0]["Condition"]
        cond["In"]["Values"] = [[{"Literal": {"Value": "'Raw'"}}]]
    _fmt(client, fn)


def format_unlocked(client: Path) -> None:
    _fmt(client, lambda d: d["filterConfig"]["filters"][0].update(isLockedInViewMode=False))


def format_duplicates(client: Path) -> None:
    def fn(d):
        f = json.loads(json.dumps(d["filterConfig"]["filters"][0]))
        f["name"] = "format_selector_filter_copy"
        d["filterConfig"]["filters"].append(f)
    _fmt(client, fn)


# -- stale placeholder bindings -----------------------------------------------------
def stale_series(client: Path) -> None:
    """The combo Series role declares y-Plot Specific 1 (offers [z_space]) but
    projects [z]."""
    def fn(d):
        p = d["visual"]["query"]["queryState"]["Series"]["projections"][0]
        p["field"]["Column"]["Property"] = "z"
        p["queryRef"] = "#Report Measures.z"
    _edit(_v(client, "combo_main"), fn)


def stale_ambiguous(client: Path) -> None:
    """A bookmark container whose Rows role declares two axes that offer
    different placeholders: reported as skipped, never a failure."""
    def fn(d):
        col = lambda e, p: {"Column": {"Expression": {"SourceRef": {"Entity": e}}, "Property": p}}
        d["explorationState"]["sections"][MAIN]["visualContainers"]["matrix_main"] = {"singleVisual": {
            "visualType": "pivotTable",
            "projections": {"Rows": [dict(col("#Report Measures", "z"), queryRef="#Report Measures.z")]},
            "parameters": {"Rows": [
                {"expr": col("y-Plot Specific 1", "y-Plot Specific 1 Fields"), "index": 0, "length": 1},
                {"expr": col("y-Selector 2", "y-Selector 2 Fields"), "index": 0, "length": 1}]}}}
    _edit(_r(client) / "bookmarks" / "bA00000000000000000a.bookmark.json", fn)


VARIANTS: dict[str, Callable[[Path], None]] = {
    "rule1-ungated": rule1_ungated,
    "rule3-missing": rule3_missing,
    "theme-base-only": theme_base_only,
    "theme-empty": theme_empty,
    "theme-hex": theme_hex,
    "rule8-renamed": rule8_renamed,
    "rule8-no-groups": rule8_no_groups,
    "position-missing-y": position_missing_y,
    "ycombo-bad-name": ycombo_bad_name,
    "ycombo-orphan": ycombo_orphan,
    "format-no-filter-config": format_no_filter_config,
    "format-raw": format_raw,
    "format-unlocked": format_unlocked,
    "format-duplicates": format_duplicates,
    "stale-series": stale_series,
    "stale-ambiguous": stale_ambiguous,
}

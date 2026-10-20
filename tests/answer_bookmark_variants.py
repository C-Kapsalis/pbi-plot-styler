"""Defect variants of the answer-bookmark sample report.

Each variant below injects exactly one defect into a copy of the sample
report (tests/fixtures/spinout_02_db/-Insights.Report).

Pure data helpers: no tool imports.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

MAIN_PAGE = "8ae41e673f3fd0bc78e4"
MATRIX = "cd92884eb63c893f0993"
Y_ROWS = "a66437fdd921b68b0bc7"
PARAM_SLICER = {
    "x-Plot Specific 1": "654684d46df1873d7af8",
    "x-Plot Specific 2": "d93bbe99cd9d524857e7",
    "x-Selector 2": "27ce5533384712bd1485",
    "y-Selector 2": Y_ROWS,
}
ROW_DROPDOWNS = ["7e9750aa86623b171790", "68d1b60f8adc66215a80",
                 "c95d684e89dc0a1fca6e", "4130103a3ac592a721ee"]
NAVIGATOR = "9f8e7d6c5b4a39281706"
INHERITED = ("!Conversions #", "!CVR", "!CPC", "Campaign Actual")
CATEGORY_PREFIXES = ("CRM Deals |", "CRM Activities |", "CRM Email |", "API |",
                     "Accounts |", "Organizations |", "Users |")
PIPELINE = "b1a2c3d4e5f60718293a"       # "CRM Deals | Pipeline" (clean)
OWNERS = "c2b3d4e5f6a708192a3b"         # "CRM Deals | Owners" (T1, baselined)
DATES = "d3c4e5f6a7b8091a2b3c"          # "Date presets" (outside the prefixes)


def _p(report: Path, *parts: str) -> Path:
    return report.joinpath("definition", *parts)


def _edit(path: Path, fn: Callable[[dict], None]) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    fn(data)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _bm(report: Path, name: str = PIPELINE) -> Path:
    return _p(report, "bookmarks", f"{name}.bookmark.json")


def _matrix_page(report: Path) -> Path:
    return _p(report, "pages", MAIN_PAGE, "visuals", MATRIX, "visual.json")


def _section(bm: dict) -> dict:
    st = bm["explorationState"]
    return st["sections"][st["activeSection"]]


def _mx(bm: dict) -> dict:
    return _section(bm)["visualContainers"][MATRIX]["singleVisual"]


def _col(entity: str, prop: str) -> dict:
    return {"Column": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}


# -- bookmark level ------------------------------------------------------------
def no_prefix_match(report: Path) -> None:
    """Every bookmark renamed off the category prefixes (vacuity)."""
    for f in _p(report, "bookmarks").glob("*.bookmark.json"):
        _edit(f, lambda d: d.update(displayName=d["displayName"].replace(" | ", " - ")))


def t1_unscoped(report: Path) -> None:
    _edit(_bm(report), lambda d: d["options"].update(targetVisualNames=[MATRIX]))


def t1_missing_key(report: Path) -> None:
    _edit(_bm(report), lambda d: d["options"].pop("targetVisualNames"))


def t7_no_literal(report: Path) -> None:
    def fn(d):
        _section(d)["filters"]["byExpr"][0].pop("filter")
    _edit(_bm(report), fn)


def t8_unregistered(report: Path) -> None:
    def fn(d):
        d["items"][0]["children"].remove(PIPELINE)
        d["items"].append({"name": PIPELINE})
    _edit(_p(report, "bookmarks", "bookmarks.json"), fn)


# -- capture level -------------------------------------------------------------
def t3_hidden(report: Path) -> None:
    _edit(_bm(report), lambda d: _mx(d).update(display={"mode": "hidden"}))


def t3_not_captured(report: Path) -> None:
    _edit(_bm(report), lambda d: _section(d)["visualContainers"].pop(MATRIX))


def t4_rows_mismatch(report: Path) -> None:
    def fn(d):
        _mx(d)["projections"]["Rows"][0]["Column"]["Property"] = "Deal Owner"
    _edit(_bm(report), fn)


def t4_inherited(report: Path) -> None:
    def fn(d):
        _mx(d)["prototypeQuery"] = {"Version": 2, "Select": [
            {**_col("_Campaigns", "Campaign Actual"), "Name": "_Campaigns.Campaign Actual"}]}
    _edit(_bm(report), fn)


def t5_active_values(report: Path) -> None:
    def fn(d):
        _mx(d)["activeProjections"]["Values"] = [_col("CRM Deals", "Won Deals #")]
    _edit(_bm(report), fn)


def t5_expansion(report: Path) -> None:
    def fn(d):
        _mx(d)["expansionStates"] = [{"roles": ["Rows"], "levels": [
            {"queryRefs": ["CRM Deals.Deal Stage"], "isCollapsed": True}]}]
    _edit(_bm(report), fn)


def t9_second_slot(report: Path) -> None:
    def fn(d):
        _mx(d)["parameters"]["Values"][1]["index"] = 0
    _edit(_bm(report), fn)


def t9_two_params(report: Path) -> None:
    def fn(d):
        _mx(d)["parameters"]["Values"].pop()
    _edit(_bm(report), fn)


def t9_order(report: Path) -> None:
    def fn(d):
        vals = _mx(d)["projections"]["Values"]
        vals[0], vals[1] = vals[1], vals[0]
    _edit(_bm(report), fn)


def t10_no_mirror(report: Path) -> None:
    _edit(_bm(report), lambda d: _section(d)["visualContainers"].pop(ROW_DROPDOWNS[0]))


# -- page level ----------------------------------------------------------------
def p1_raw_measure(report: Path) -> None:
    def fn(d):
        d["visual"]["query"]["queryState"]["Values"]["projections"][3] = {
            "field": {"Measure": {"Expression": {"SourceRef": {"Entity": "CRM Deals"}},
                                  "Property": "Won Deals #"}},
            "queryRef": "CRM Deals.Won Deals #"}
    _edit(_matrix_page(report), fn)


def p2_dangling(report: Path) -> None:
    def fn(d):
        props = d["visual"]["objects"]["bookmarks"][0]["properties"]
        props["selectedBookmark"]["expr"]["Literal"]["Value"] = "'0123456789abcdef0123'"
    _edit(_p(report, "pages", MAIN_PAGE, "visuals", NAVIGATOR, "visual.json"), fn)


def _set_slots(report: Path, slots: list[tuple[str, int, int]]) -> None:
    def fn(d):
        blk = d["visual"]["query"]["queryState"]["Values"]
        blk["fieldParameters"] = [
            {"parameterExpr": _col(e, f"{e} Fields"), "index": i, "length": n}
            for e, i, n in slots]
    _edit(_matrix_page(report), fn)


def p3_all_at_zero(report: Path) -> None:
    _set_slots(report, [("x-Plot Specific 1", 0, 1), ("x-Plot Specific 2", 0, 1),
                        ("x-Selector 2", 0, 1)])


def p3_two_slot_overlap(report: Path) -> None:
    _set_slots(report, [("x-Plot Specific 1", 0, 2), ("x-Plot Specific 2", 0, 2)])


def p3_same_entity(report: Path) -> None:
    _set_slots(report, [("x-Plot Specific 1", 0, 1), ("x-Plot Specific 1", 0, 1)])


def p3_range(report: Path) -> None:
    _set_slots(report, [("x-Plot Specific 1", 0, 1), ("x-Plot Specific 2", 1, 1),
                        ("x-Selector 2", 3, 2)])


#: variant -> (mutation, the test it makes fail, expected new findings as
#: {IDS key: count}). The p3-two-slot-overlap and p3-same-entity variants
#: change the declared Values parameters, so T9 also fails for both answer
#: bookmarks. Counts are one per finding subject; for P3 each overlapping slot
#: is its own finding (the stricter FPM001 rule). The slot check compares the
#: Rows and the Values slots, so t4-rows-mismatch also fails the Rows slot map.
VARIANTS: dict[str, tuple[Callable[[Path], None], str, dict[str, int]]] = {
    "t1-unscoped": (t1_unscoped, "TestBookmarkLevel::test_t1_targets_all_visuals", {"T1": 1}),
    "t1-missing-key": (t1_missing_key, "TestBookmarkLevel::test_t1_targets_all_visuals", {"T1": 1}),
    "t7-no-literal": (t7_no_literal, "TestBookmarkLevel::test_t7_analysis_category_pinned", {"T7": 1}),
    "t8-unregistered": (t8_unregistered, "TestBookmarkLevel::test_t8_registered_under_a_submenu", {"T8": 1}),
    "t3-hidden": (t3_hidden, "TestVisualCaptureLevel::test_t3_matrix_captured_and_visible", {"T3": 1}),
    "t3-not-captured": (t3_not_captured, "TestVisualCaptureLevel::test_t3_matrix_captured_and_visible", {"T3": 1}),
    "t4-rows-mismatch": (t4_rows_mismatch, "TestVisualCaptureLevel::test_t4_rows_are_this_bookmarks_own", {"T4": 1, "T9": 1}),
    "t4-inherited": (t4_inherited, "TestVisualCaptureLevel::test_t4_rows_are_this_bookmarks_own", {"T4": 1}),
    "t5-active-values": (t5_active_values, "TestVisualCaptureLevel::test_t5_matrix_capture_shape", {"T5": 1}),
    "t5-expansion": (t5_expansion, "TestVisualCaptureLevel::test_t5_matrix_capture_shape", {"T5": 1}),
    "t9-second-slot": (t9_second_slot, "TestVisualCaptureLevel::test_t9_every_declared_values_parameter_is_resolved", {"T9": 1}),
    "t9-two-params": (t9_two_params, "TestVisualCaptureLevel::test_t9_every_declared_values_parameter_is_resolved", {"T9": 1}),
    "t9-order": (t9_order, "TestVisualCaptureLevel::test_t9_every_declared_values_parameter_is_resolved", {"T9": 1}),
    "t10-no-mirror": (t10_no_mirror, "TestVisualCaptureLevel::test_t10_row_dimensions_have_dropdown_filters", {"T10": 1}),
    "p1-raw-measure": (p1_raw_measure, "TestPageLevel::test_p1_parameter_wells_carry_no_raw_measures", {"P1": 1}),
    "p2-dangling": (p2_dangling, "TestPageLevel::test_p2_navigator_references_resolve", {"P2": 1}),
    "p3-all-at-zero": (p3_all_at_zero, "TestPageLevel::test_p3_parameter_slot_ranges_do_not_overlap", {"P3-overlap": 2}),
    "p3-two-slot-overlap": (p3_two_slot_overlap, "TestPageLevel::test_p3_parameter_slot_ranges_do_not_overlap", {"P3-overlap": 2, "T9": 2}),
    "p3-same-entity": (p3_same_entity, "TestPageLevel::test_p3_parameter_slot_ranges_do_not_overlap", {"P3-overlap": 1, "T9": 2}),
    "p3-range": (p3_range, "TestPageLevel::test_p3_parameter_slot_ranges_do_not_overlap", {"P3-range": 1}),
}

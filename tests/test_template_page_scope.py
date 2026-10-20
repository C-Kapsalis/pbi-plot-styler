"""Canvas ("typical template") page scope for the f-Slicer / f-All gates.

The gates are imposed only on pages
that carry the standard canvas (at least one matrix AND at least one
line-and-stacked-column chart) and never on a page whose name contains
'cohort' or 'ltv'. Three consumers must agree: the canvas-page / selector-
slicer API, the slicer-gates rule (foundation rule 1, with its fixer) and the
slicer-mode-gates rule. A synthetic four-page report pins all three: only the
plain template page is reported or patched.
"""
import json
from pathlib import Path

import pytest

from pbi_plot_styler.canvas import canvas_pages, selector_slicers
from cli_helpers import run

# page dir name -> (display name, visual types besides the selector slicer)
PAGES = {
    "p_template": ("Backend", ["pivotTable", "lineStackedColumnComboChart"]),
    "p_cohort": ("Subscription Cohorts", ["pivotTable", "lineStackedColumnComboChart"]),
    "p_ltv": ("LTV:CAC", ["pivotTable", "lineStackedColumnComboChart"]),
    "p_plain": ("Overview", ["pivotTable"]),  # no combo chart -> not the template
}


def _report_slicer(name: str) -> dict:
    return {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/1.0.0/schema.json",
        "name": name,
        "position": {"x": 0, "y": 0, "z": 0, "width": 100, "height": 40},
        "visual": {
            "visualType": "slicer",
            "query": {"queryState": {"Values": {"projections": [
                {"field": {"Column": {"Expression": {"SourceRef": {"Entity": "x-Selector 1"}}, "Property": "x-Selector 1 Fields"}},
                 "queryRef": "x-Selector 1.x-Selector 1 Fields"}]}}},
            "objects": {"data": [{"properties": {"mode": {"expr": {"Literal": {"Value": "'Dropdown'"}}}}}]},
        },
    }


def _plain_visual(name: str, vtype: str) -> dict:
    return {"name": name, "position": {"x": 0, "y": 0, "z": 0, "width": 100, "height": 100},
            "visual": {"visualType": vtype}}


def _bookmark_vc(vc_id: str) -> dict:
    return {"singleVisual": {"visualType": "slicer", "activeProjections": {"Values": [
        {"Column": {"Expression": {"SourceRef": {"Entity": "x-Selector 1"}}, "Property": "x-Selector 1 Fields"}}]}}}


@pytest.fixture
def synthetic_report(tmp_path: Path) -> Path:
    client = tmp_path / "test_client_db"
    # sibling model declaring both gate measures, so the fixers resolve `f-Filters`
    tables = client / "Growth.SemanticModel" / "definition" / "tables"
    tables.mkdir(parents=True)
    (tables / "f-Filters.tmdl").write_text(
        "table 'f-Filters'\n\tmeasure 'f-Slicer' = 1\n\tmeasure 'f-All' = 1\n", encoding="utf-8")
    report = client / "-Test.Report"
    (report / "definition").mkdir(parents=True)
    (report / "definition.pbir").write_text(json.dumps(
        {"datasetReference": {"byPath": {"path": "../Growth.SemanticModel"}}}), encoding="utf-8")
    (report / "definition" / "report.json").write_text(json.dumps({"filterConfig": {"filters": []}}), encoding="utf-8")
    sections = {}
    for pid, (display, types) in PAGES.items():
        pdir = report / "definition" / "pages" / pid
        (pdir / "visuals").mkdir(parents=True)
        (pdir / "page.json").write_text(json.dumps({"name": pid, "displayName": display}), encoding="utf-8")
        slicer_id = f"slicer_{pid}"
        (pdir / "visuals" / slicer_id).mkdir()
        (pdir / "visuals" / slicer_id / "visual.json").write_text(json.dumps(_report_slicer(slicer_id)), encoding="utf-8")
        for k, vt in enumerate(types):
            vid = f"v{k}_{pid}"
            (pdir / "visuals" / vid).mkdir()
            (pdir / "visuals" / vid / "visual.json").write_text(json.dumps(_plain_visual(vid, vt)), encoding="utf-8")
        sections[pid] = {"visualContainers": {slicer_id: _bookmark_vc(slicer_id)}}
    (report / "definition" / "bookmarks").mkdir()
    (report / "definition" / "bookmarks" / "b1.bookmark.json").write_text(json.dumps(
        {"name": "b1", "displayName": "1. Test", "explorationState": {"sections": sections}}), encoding="utf-8")
    return report


def _has_visual_gate(vjson: Path, prop: str) -> bool:
    data = json.loads(vjson.read_text(encoding="utf-8"))
    for f in data.get("filterConfig", {}).get("filters", []):
        bound = f.get("field", {}).get("Measure", {})
        if bound.get("Property") == prop:
            return True
    return False


def _bookmark_pages_with_gate(bj: Path) -> set:
    data = json.loads(bj.read_text(encoding="utf-8"))
    out = set()
    for pid, sec in data["explorationState"]["sections"].items():
        for vc in sec["visualContainers"].values():
            if (vc.get("filters") or {}).get("byName"):
                out.add(pid)
    return out


@pytest.mark.layer3_5
@pytest.mark.visual_architecture
class TestTypicalTemplatePageScope:

    def test_parser_scopes_rule_1_to_template_pages(self, synthetic_report):
        assert canvas_pages(synthetic_report) == ["p_template"]
        scoped = {s.page_id for s in selector_slicers(synthetic_report)}
        assert scoped == {"p_template"}
        unscoped = {s.page_id for s in selector_slicers(synthetic_report, canvas_only=False)}
        assert unscoped == set(PAGES)

    def test_f_slicer_fixer_reports_and_patches_template_page_only(self, synthetic_report):
        check = run("check", synthetic_report, "--rule", "slicer-gates")
        assert check.exit_code == 1, check.output
        assert "slicer_p_template" in check.output
        for pid in ("p_cohort", "p_ltv", "p_plain"):
            assert f"slicer_{pid}" not in check.output, check.output

        apply = run("check", synthetic_report, "--rule", "slicer-gates", "--fix")
        assert apply.exit_code == 0, apply.output
        pages = synthetic_report / "definition" / "pages"
        assert _has_visual_gate(pages / "p_template" / "visuals" / "slicer_p_template" / "visual.json", "f-Slicer")
        for pid in ("p_cohort", "p_ltv", "p_plain"):
            assert not _has_visual_gate(pages / pid / "visuals" / f"slicer_{pid}" / "visual.json", "f-Slicer"), pid
        assert _bookmark_pages_with_gate(synthetic_report / "definition" / "bookmarks" / "b1.bookmark.json") == {"p_template"}

    def test_slicer_mode_fixer_patches_template_page_only(self, synthetic_report):
        apply = run("check", synthetic_report, "--rule", "slicer-mode-gates", "--fix")
        assert apply.exit_code == 0, apply.output
        pages = synthetic_report / "definition" / "pages"
        # Dropdown mode -> f-Slicer gate, on the template page only
        assert _has_visual_gate(pages / "p_template" / "visuals" / "slicer_p_template" / "visual.json", "f-Slicer")
        for pid in ("p_cohort", "p_ltv", "p_plain"):
            assert not _has_visual_gate(pages / pid / "visuals" / f"slicer_{pid}" / "visual.json", "f-Slicer"), pid
        assert _bookmark_pages_with_gate(synthetic_report / "definition" / "bookmarks" / "b1.bookmark.json") == {"p_template"}

"""F-slicer-mode-gates: fictional cases 1-6 (``check --rule slicer-mode-gates [--fix]``).

New tests; the original template-page-scope test is ported in
test_template_page_scope.py. Fixture ``fixtures/mode-gates``: canvas page
(pivotTable + lineStackedColumnComboChart) with a compliant dropdown slicer,
a Basic (list) slicer without a gate, a Between slicer, and a dropdown slicer
whose active gate is bound to ``w-Visuals Filters``; the bookmark carries a
passive ``byExpr`` entry naming ``f-Slicer`` on ``w-Visuals Filters``.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from ported_helpers import IDS, check_json, copy_fixture, load, of, run

PAGE = "6c6d6e6f606162636465"


@pytest.fixture
def client(tmp_path: Path) -> Path:
    return copy_fixture("mode-gates", tmp_path)


def _report(client: Path) -> Path:
    return client / "-Canvas.Report"


def _visual(client: Path, vid: str) -> dict:
    return load(_report(client) / "definition" / "pages" / PAGE / "visuals" / vid / "visual.json")


def _gates(visual: dict) -> list[dict]:
    return [f for f in (visual.get("filterConfig") or {}).get("filters") or []
            if "Measure" in (f.get("field") or {})]


def _bookmark(client: Path) -> dict:
    return load(_report(client) / "definition" / "bookmarks" / "e0e0e0e0e0e0e0e0e0e0.bookmark.json")


def _snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def _fix(path: Path, rule: str):
    return run("check", path, "--rule", rule, "--fix")


def test_check_reports_each_problem(client):
    payload = check_json(_report(client), "slicer-mode-gates")
    assert payload["exit_code"] == 1
    gate = of(payload, "MODE-gate")
    assert [f["subject"] for f in gate if "list01" in f["subject"]], gate          # case 1
    assert not [f for f in payload["findings"] if "range01" in f["subject"]]       # case 2
    assert not [f for f in payload["findings"] if "dropdown01" in f["subject"]]    # already ok
    assert [f for f in of(payload, "MODE-wrong-entity") if "dropdown02" in f["subject"]]  # case 3
    assert len(of(payload, "MODE-stale-ref")) >= 1                                 # case 4


def test_case1_basic_slicer_gains_active_f_all_gate(client):
    assert _fix(_report(client), "slicer-mode-gates").exit_code == 0
    gates = _gates(_visual(client, "list01"))
    assert len(gates) == 1
    g = gates[0]
    assert g["field"]["Measure"]["Property"] == "f-All"
    assert g["field"]["Measure"]["Expression"]["SourceRef"]["Entity"] == "f-Filters"
    comp = g["filter"]["Where"][0]["Condition"]["Comparison"]
    assert comp["ComparisonKind"] == 1 and comp["Right"]["Literal"]["Value"] == "0L"
    assert g["type"] == "Advanced" and g["howCreated"] == "User"


def test_case2_between_slicer_untouched(client):
    path = _report(client) / "definition" / "pages" / PAGE / "visuals" / "range01" / "visual.json"
    before = path.read_bytes()
    assert _fix(_report(client), "slicer-mode-gates").exit_code == 0
    assert path.read_bytes() == before


def test_case3_wrong_entity_is_repointed(client):
    assert _fix(_report(client), "slicer-mode-gates").exit_code == 0
    g = _gates(_visual(client, "dropdown02"))[0]
    assert g["name"] == "b0b0b0b0b0b0b0b0b0b0"   # name kept
    assert g["field"]["Measure"]["Expression"]["SourceRef"]["Entity"] == "f-Filters"
    assert g["field"]["Measure"]["Property"] == "f-Slicer"
    assert g["filter"]["From"][0]["Entity"] == "f-Filters"
    assert check_json(_report(client), "slicer-mode-gates")["exit_code"] == 0


def test_case4_passive_bookmark_reference_is_repointed(client):
    assert _fix(_report(client), "slicer-mode-gates").exit_code == 0
    entry = _bookmark(client)["explorationState"]["sections"][PAGE]["filters"]["byExpr"][0]
    assert entry["expression"]["Measure"]["Expression"]["SourceRef"]["Entity"] == "f-Filters"
    assert entry["filter"]["From"][0]["Entity"] == "f-Filters"
    assert "w-Visuals Filters" not in json.dumps(_bookmark(client))


def test_case5_no_model_declaring_both_gates(client):
    (client / "Growth.SemanticModel" / "definition" / "tables" / "f-Filters.tmdl").write_text(
        "table 'f-Filters'\n\n\tmeasure 'f-Slicer' = 1\n", encoding="utf-8")
    before = _snapshot(client)
    result = _fix(_report(client), "slicer-mode-gates")
    assert result.exit_code == 2
    assert _snapshot(client) == before


def test_case6_order_with_slicer_gate_fixer_does_not_matter(tmp_path):
    a = copy_fixture("gate-order", tmp_path / "a")
    b = copy_fixture("gate-order", tmp_path / "b")
    assert _fix(a / "-Canvas.Report", "slicer-gates").exit_code == 0
    assert _fix(a / "-Canvas.Report", "slicer-mode-gates").exit_code == 0
    assert _fix(b / "-Canvas.Report", "slicer-mode-gates").exit_code == 0
    assert _fix(b / "-Canvas.Report", "slicer-gates").exit_code == 0
    assert _snapshot(a) == _snapshot(b)
    # and the shared result carries the active gate on both sides
    v = load(a / "-Canvas.Report/definition/pages/7a7b7c7d7e7f70717273/visuals/dropdown01/visual.json")
    g = _gates(v)[0]
    assert g["name"] == "f1f1f1f1f1f1f1f1f1f1"
    assert g["filter"]["Where"][0]["Condition"]["Comparison"]["Right"]["Literal"]["Value"] == "0L"


def test_fix_is_idempotent(client):
    assert _fix(_report(client), "slicer-mode-gates").exit_code == 0
    first = _snapshot(client)
    assert _fix(_report(client), "slicer-mode-gates").exit_code == 0
    assert _snapshot(client) == first

"""Gate rules: any active gate counts, names, aliases, patterns, sweeps, heuristic."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from cli_helpers import IDS, check_json, copy_fixture, load, of, run, write_toml
from pbi_plot_styler.canvas import Settings, settings_from_mapping

PAGE = "7a7b7c7d7e7f70717273"
BOOKMARK = "f2f2f2f2f2f2f2f2f2f2.bookmark.json"


def _report(root: Path) -> Path:
    return root / "-Canvas.Report"


def _bm_path(root: Path) -> Path:
    return _report(root) / "definition" / "bookmarks" / BOOKMARK


def _by_name(root: Path) -> dict:
    data = load(_bm_path(root))
    return data["explorationState"]["sections"][PAGE]["visualContainers"]["dropdown01"]["filters"]["byName"]


def _edit_bm(root: Path, fn) -> None:
    data = load(_bm_path(root))
    fn(data["explorationState"]["sections"][PAGE]["visualContainers"]["dropdown01"])
    _bm_path(root).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _active(name: str) -> dict:
    return {"name": name, "type": "Advanced", "filter": {"Version": 2, "From": [
        {"Name": "f", "Entity": "f-Filters", "Type": 0}], "Where": [{"Condition": {"Comparison": {
            "ComparisonKind": 1, "Left": {"Measure": {"Expression": {"SourceRef": {"Source": "f"}},
                                                      "Property": "f-Slicer"}},
            "Right": {"Literal": {"Value": "0L"}}}}}]},
        "expression": {"Measure": {"Expression": {"SourceRef": {"Entity": "f-Filters"}},
                                   "Property": "f-Slicer"}}, "howCreated": 1}


def _snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


# -- SC48 -------------------------------------------------------------------------
def test_a_capture_with_any_active_gate_is_compliant(tmp_path):
    root = copy_fixture("gate-order", tmp_path)
    _edit_bm(root, lambda c: c["filters"]["byName"].update(zz_active=_active("zz_active")))
    payload = check_json(_report(root), "slicer-gates")
    assert not of(payload, "RULE1-bookmark")
    before = _bm_path(root).read_bytes()
    assert run("check", _report(root), "--rule", "slicer-gates", "--fix").exit_code == 0
    assert _bm_path(root).read_bytes() == before


def test_a_replaced_bookmark_gate_is_named_like_its_key(tmp_path):
    for rule in ("slicer-gates", "slicer-mode-gates"):
        root = copy_fixture("gate-order", tmp_path / rule)
        _edit_bm(root, lambda c: c["filters"]["byName"]["f1f1f1f1f1f1f1f1f1f1"].update(name="other"))
        assert run("check", _report(root), "--rule", rule, "--fix").exit_code == 0
        assert _by_name(root)["f1f1f1f1f1f1f1f1f1f1"]["name"] == "f1f1f1f1f1f1f1f1f1f1", rule


def test_a_new_bookmark_gate_has_the_same_name_in_either_fixer_order(tmp_path):
    a = copy_fixture("gate-order", tmp_path / "a")
    b = copy_fixture("gate-order", tmp_path / "b")
    for root in (a, b):
        _edit_bm(root, lambda c: c.pop("filters"))
    for rule in ("slicer-gates", "slicer-mode-gates"):
        assert run("check", _report(a), "--rule", rule, "--fix").exit_code == 0
    for rule in ("slicer-mode-gates", "slicer-gates"):
        assert run("check", _report(b), "--rule", rule, "--fix").exit_code == 0
    assert _snapshot(a) == _snapshot(b)
    assert len(_by_name(a)) == 1


def test_gates_use_the_default_host_tables_alias_letter(tmp_path):
    root = copy_fixture("gate-order", tmp_path)
    tables = root / "Growth.SemanticModel" / "definition" / "tables"
    (tables / "f-Filters.tmdl").rename(tables / "Gate Measures.tmdl")
    text = (tables / "Gate Measures.tmdl").read_text(encoding="utf-8")
    (tables / "Gate Measures.tmdl").write_text(text.replace("table 'f-Filters'", "table 'Gate Measures'"),
                                               encoding="utf-8")
    _edit_bm(root, lambda c: c.pop("filters"))
    assert run("check", _report(root), "--rule", "slicer-gates", "--fix").exit_code == 0
    gate = next(iter(_by_name(root).values()))
    assert gate["filter"]["From"] == [{"Name": "f", "Entity": "Gate Measures", "Type": 0}]


def test_selector_table_patterns_ignore_case():
    settings = settings_from_mapping({"canvas": {"selector_tables": ["X-SEL*"]}})
    assert settings.is_selector_table("x-Selector 1")
    assert Settings().is_selector_table("X-Selector 1")


# -- SC25: a sweep continues past a report without the gate measure -----------------
def test_the_gate_fixer_continues_past_a_report_it_cannot_fix(tmp_path):
    root = tmp_path / "client"
    first = copy_fixture("gate-order", root / "a")
    second = copy_fixture("gate-order", root / "b")
    gates = first / "Growth.SemanticModel" / "definition" / "tables" / "f-Filters.tmdl"
    gates.write_text("table 'f-Filters'\n\n\tmeasure 'f-All' = 1\n", encoding="utf-8")
    before = _snapshot(first / "-Canvas.Report")
    result = run("check", root, "--rule", "slicer-gates", "--fix")
    assert result.exit_code == 1, result.output
    assert "ERROR (" in result.output and "a/gate-order/-Canvas.Report" in result.output
    assert "skipping all violating slicers under this report." in result.output
    assert _snapshot(first / "-Canvas.Report") == before
    assert check_json(_report(second), "slicer-gates")["exit_code"] == 0


# -- SC49: the name heuristic never drives the fix ---------------------------------
def test_the_name_heuristic_adds_findings_but_not_fixes(tmp_path):
    root = copy_fixture("gate-order", tmp_path)
    visuals = _report(root) / "definition" / "pages" / PAGE / "visuals"
    data = load(visuals / "dropdown01" / "visual.json")
    data["name"] = "region selector slicer"
    data.pop("filterConfig")
    data["visual"]["query"]["queryState"]["Values"]["projections"][0]["field"]["Column"][
        "Expression"]["SourceRef"]["Entity"] = "Regions"
    (visuals / "named").mkdir()
    (visuals / "named" / "visual.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    config = write_toml(tmp_path / "plotstyler.toml", {"gates": {"name_heuristic": True}})
    payload = check_json(_report(root), "slicer-gates", config=config)
    assert "region selector slicer" in [f["subject"] for f in of(payload, "RULE1-visual")]
    before = (visuals / "named" / "visual.json").read_bytes()
    run("check", _report(root), "--rule", "slicer-gates", "--fix", "--config", config)
    assert (visuals / "named" / "visual.json").read_bytes() == before


# -- SC52: normalisation leaves unrelated aliases -----------------------------------
def test_normalisation_rewrites_only_the_gate_alias(tmp_path):
    client = copy_fixture("mode-gates", tmp_path)
    path = client / "-Canvas.Report" / "definition" / "bookmarks" / "e0e0e0e0e0e0e0e0e0e0.bookmark.json"
    data = load(path)
    entry = data["explorationState"]["sections"]["6c6d6e6f606162636465"]["filters"]["byExpr"][0]
    entry["filter"]["From"].append({"Name": "d", "Entity": "Dates", "Type": 0})
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    assert run("check", client / "-Canvas.Report", "--rule", "slicer-mode-gates", "--fix").exit_code == 0
    entry = load(path)["explorationState"]["sections"]["6c6d6e6f606162636465"]["filters"]["byExpr"][0]
    assert entry["filter"]["From"] == [{"Name": "w", "Entity": "f-Filters", "Type": 0},
                                       {"Name": "d", "Entity": "Dates", "Type": 0}]

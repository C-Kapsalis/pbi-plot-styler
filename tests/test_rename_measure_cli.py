"""``rename-measure``: column look-alikes, escaped literals, the CLI and file layout."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from cli_helpers import run

from pbi_plot_styler.rename import count_tree, rewrite_tree

BOM = b"\xef\xbb\xbf"


def _column_projection(name: str) -> dict:
    return {
        "field": {"Column": {"Expression": {"SourceRef": {"Entity": "Dim"}}, "Property": name}},
        "queryRef": f"Dim.{name}",
        "nativeQueryRef": name,
        "displayName": name,
    }


def _measure_projection(name: str) -> dict:
    return {
        "field": {"Measure": {"Expression": {"SourceRef": {"Entity": "Facts"}}, "Property": name}},
        "queryRef": f"Facts.{name}",
        "nativeQueryRef": name,
        "displayName": name,
    }


def test_a_full_column_projection_named_like_the_measure_is_untouched():
    node = {"projections": [_column_projection("Spend")]}
    before = copy.deepcopy(node)
    assert count_tree(node, "Spend") == 0
    assert rewrite_tree(node, "Spend", "Ad Spend") == 0
    assert node == before


def test_the_measure_projection_beside_it_is_still_renamed():
    node = {"projections": [_column_projection("Spend"), _measure_projection("Spend")]}
    assert rewrite_tree(node, "Spend", "Ad Spend") == 4
    column, measure = node["projections"]
    assert column == _column_projection("Spend")
    assert measure == _measure_projection("Ad Spend")


def test_selection_literal_with_an_apostrophe_is_found_and_written_escaped():
    lit = {"Literal": {"Value": "'''#Report Measures''[Rep''''s Spend]'"}}
    assert count_tree(lit, "Rep's Spend") == 1
    other = {"Literal": {"Value": "'''#Report Measures''[CPA]'"}}
    assert rewrite_tree(other, "CPA", "Rep's CPA") == 1
    assert other["Literal"]["Value"] == "'''#Report Measures''[Rep''''s CPA]'"


def test_selection_literal_with_a_closing_bracket_is_found_and_written_doubled():
    lit = {"Literal": {"Value": "'''T''[A]]B]'"}}
    assert count_tree(lit, "A]B") == 1
    assert rewrite_tree(lit, "A]B", "C]D") == 1
    assert lit["Literal"]["Value"] == "'''T''[C]]D]'"


# -- the command ----------------------------------------------------------------
def _project(tmp_path: Path, *, bom: bool, crlf: bool) -> tuple[Path, Path]:
    model = tmp_path / "Shop.SemanticModel"
    model.mkdir()
    visual = tmp_path / "Shop.Report" / "definition" / "pages" / "p1" / "visuals" / "v1" / "visual.json"
    visual.parent.mkdir(parents=True)
    data = {"name": "v1", "visual": {"query": {"queryState": {"Y": {"projections": [
        _measure_projection("Old"), _column_projection("Old")]}}}}}
    text = json.dumps(data, indent=2) + "\n"
    if crlf:
        text = text.replace("\n", "\r\n")
    visual.write_bytes((BOM if bom else b"") + text.encode("utf-8"))
    return model, visual


def test_cli_dry_run_counts_and_writes_nothing(tmp_path):
    model, visual = _project(tmp_path, bom=False, crlf=False)
    before = visual.read_bytes()
    result = run("rename-measure", "Old", "New", "--model", model, "--dry-run")
    assert result.exit_code == 0, result.output
    assert "DRY RUN: 4 reference(s) to [Old] in 1 report(s)." in result.output
    assert visual.read_bytes() == before


def test_cli_apply_matches_the_dry_run_count(tmp_path):
    model, visual = _project(tmp_path, bom=False, crlf=False)
    result = run("rename-measure", "Old", "New", "--model", model)
    assert result.exit_code == 0, result.output
    assert "APPLIED: 4 reference(s) renamed to [New] in 1 report(s)." in result.output
    projections = json.loads(visual.read_text(encoding="utf-8"))["visual"]["query"][
        "queryState"]["Y"]["projections"]
    assert projections == [_measure_projection("New"), _column_projection("Old")]


def test_cli_keeps_bom_and_crlf(tmp_path):
    model, visual = _project(tmp_path, bom=True, crlf=True)
    assert run("rename-measure", "Old", "New", "--model", model).exit_code == 0
    raw = visual.read_bytes()
    assert raw.startswith(BOM)
    assert b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b"")
    assert b'"New"' in raw

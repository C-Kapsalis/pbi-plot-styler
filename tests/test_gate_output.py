"""The console output of the gate and filter rules.

The gate rules print what the earlier gate scripts printed: a header per
block of findings, the source entity, and the counts. The lint framing
(``SEVERITY ID  file:``) and the closing ``Checked ...`` line stay.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from cli_helpers import copy_fixture, load, run


@pytest.fixture
def gates(tmp_path: Path) -> Path:
    return copy_fixture("gate-order", tmp_path)


@pytest.fixture
def modes(tmp_path: Path) -> Path:
    return copy_fixture("mode-gates", tmp_path)


@pytest.fixture
def client(tmp_path: Path) -> Path:
    return copy_fixture("universal", tmp_path)


def _report(root: Path) -> Path:
    return root / "-Canvas.Report"


def _model(root: Path) -> Path:
    return root / "Growth.SemanticModel"


def _help() -> str:
    """The help text with the line breaks and the hyphen breaks removed."""
    out = " ".join(run("check", "--help").output.split())
    return re.sub(r"(\w)- (\w)", r"\1-\2", out)


# -- SCX55: the gate check blocks --------------------------------------------------
def test_the_check_prints_the_two_blocks(gates):
    out = run("check", gates, "--rule", "slicer-gates").stdout
    lines = out.splitlines()
    assert lines[0] == "1/1 visual(s) missing the active gate:"
    assert lines[1].startswith("ERROR    GAT001  ")
    assert "dropdown01  (" in lines[1]
    assert lines[2] == ""
    assert lines[3] == ("1 bookmark visualContainer(s) lack the active gate "
                        "(would erase it on apply):")
    assert lines[4].startswith("ERROR    GAT002  ")
    assert "f2f2f2f2f2f2f2f2f2f2.bookmark.json -> page " in lines[4]
    assert "vc dropdown01" in lines[4]


def test_a_clean_run_says_everything_is_gated(gates):
    assert run("check", gates, "--rule", "slicer-gates", "--fix").exit_code == 0
    out = run("check", gates, "--rule", "slicer-gates").stdout
    assert ("All 1 Report slicer(s) carry active `f-Slicer > 0` gates AND all "
            "bookmarks restore them faithfully.") in out


# -- SCX56: the gate fix block -----------------------------------------------------
def test_the_fix_prints_the_source_and_the_patched_lines(gates):
    out = run("check", gates, "--rule", "slicer-gates", "--fix").stdout
    lines = out.splitlines()
    assert lines[0].endswith(": source entity = 'f-Filters'  (declared in "
                             "Growth.SemanticModel/definition/tables/f-Filters.tmdl)")
    assert lines[1] == "    patched visual dropdown01"
    assert lines[2] == "    patched bookmark f2f2f2f2f2f2f2f2f2f2.bookmark.json"
    assert lines[3] == ""
    assert lines[4] == "Patched 1/1 visual(s) and 1 bookmark file(s)."


def test_a_second_fix_says_there_is_nothing_to_do(gates):
    assert run("check", gates, "--rule", "slicer-gates", "--fix").exit_code == 0
    out = run("check", gates, "--rule", "slicer-gates", "--fix").stdout
    assert "All 1 Report slicer(s) and bookmarks already gated; nothing to do." in out


# -- SCX57: the gate that cannot be bound -------------------------------------------
def test_a_report_without_the_gate_measure_is_skipped_on_stderr(tmp_path):
    root = tmp_path / "client"
    first = copy_fixture("gate-order", root / "a")
    copy_fixture("gate-order", root / "b")
    gates = first / "Growth.SemanticModel" / "definition" / "tables" / "f-Filters.tmdl"
    gates.write_text("table 'f-Filters'\n\n\tmeasure 'f-All' = 1\n", encoding="utf-8")
    result = run("check", root, "--rule", "slicer-gates", "--fix")
    assert "ERROR (" in result.stderr
    assert "no `measure 'f-Slicer'` declaration found under " in result.stderr
    assert "The measure isn't defined — fix the model first." in result.stderr
    assert "skipping all violating slicers under this report." in result.stderr
    assert "source entity = 'f-Filters'" in result.stdout


# -- SCX58: the "nothing found" lines -----------------------------------------------
def test_a_report_without_selector_slicers(tmp_path):
    root = copy_fixture("roastery", tmp_path)
    report = root / "Roastery.Report"
    out = run("check", report, "--rule", "slicer-gates").stdout
    assert f"No Report field-parameter slicers found under {report.resolve()}" in out


def test_a_clean_format_selector_run(client):
    out = run("check", client, "--rule", "format-selector").stdout
    assert "All 1 report(s) carry the z-Selector Format filter correctly." in out


# -- SCX59 and SCX60: the mode gates -------------------------------------------------
def test_the_mode_gate_check_prints_the_source_and_the_totals(modes):
    out = run("check", modes, "--rule", "slicer-mode-gates").stdout
    assert "  gate source entity (from TMDL): 'f-Filters'" in out
    assert "  Would patch 2 visual(s) and 0 bookmark entrie(s)" in out
    assert ("  Would patch 4 stale entity reference(s) -> 'f-Filters' across 2 file(s)"
            in out)


def test_the_mode_gate_fix_prints_the_patched_counts(modes):
    out = run("check", modes, "--rule", "slicer-mode-gates", "--fix").stdout
    assert "  gate source entity (from TMDL): 'f-Filters'" in out
    assert "  Patched " in out and " visual(s) and " in out
    assert "  Patched " in out and " stale entity reference(s) -> 'f-Filters' across " in out


# -- SCX61: no table declares both gate measures --------------------------------------
def test_a_model_without_both_gate_measures(modes):
    table = _model(modes) / "definition" / "tables" / "f-Filters.tmdl"
    table.write_text(table.read_text(encoding="utf-8").replace(
        "measure 'f-All'", "measure 'f-Nothing'"), encoding="utf-8")
    for extra in ([], ["--fix"], ["--fix", "--dry-run"]):
        result = run("check", modes, "--rule", "slicer-mode-gates", *extra)
        assert result.exit_code == 2, result.output
        assert result.stderr.startswith(
            "!! could not find a table declaring both [f-Slicer] and [f-All] for ")


# -- SCX62 and SCX63: the format selector ---------------------------------------------
def test_the_format_selector_prints_the_header_and_the_reason(client):
    path = client / "-Report.Report" / "definition" / "report.json"
    data = load(path)
    data["filterConfig"] = {"filters": []}
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    out = run("check", client, "--rule", "format-selector").stdout
    assert "1/1 report(s) missing or misconfigured filter:" in out
    assert (f"{path.resolve()}: no report-level filter on "
            f"z-Selector Format[Selector Format]") in out


def test_the_format_selector_fix_prints_the_patched_line(client):
    path = client / "-Report.Report" / "definition" / "report.json"
    data = load(path)
    data["filterConfig"] = {"filters": []}
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    out = run("check", client, "--rule", "format-selector", "--fix").stdout
    assert (f"  {path.resolve()}: patched (no report-level filter on "
            f"z-Selector Format[Selector Format])") in out
    assert "Patched 1/1 report(s)." in out


# -- SCX64 and SCX65: the stale placeholders --------------------------------------------
def test_a_clean_placeholder_run_names_the_folder(gates):
    out = run("check", gates, "--rule", "stale-placeholders").stdout
    assert f"No stale placeholder bindings under {gates.name}." in out


# -- SCX66: a path that does not exist ---------------------------------------------------
def test_a_path_that_does_not_exist(tmp_path):
    missing = tmp_path / "nope"
    result = run("check", missing, "--rule", "format-selector")
    assert result.exit_code == 2
    assert result.stderr == f"ERROR: {missing.resolve()} does not exist\n"
    assert result.stdout == ""


# -- SCX67: the rule help -----------------------------------------------------------------
def test_the_help_carries_the_rule_descriptions():
    out = _help()
    assert ("Enforce the `f-Slicer > 0` visual-level gate on every Report "
            "field-parameter slicer (foundation rule #1).") in out
    assert "Check: scan only; exit 1 if any Report slicer lacks the gate." in out
    assert "Fix: inject the gate into every violating slicer in place." in out
    assert "Enforce the owner's slicer-gate convention across a report." in out
    assert "Dropdown slicer -> visual-level filter [f-Slicer] > 0" in out
    assert "Vertical-list slicer -> visual-level filter [f-All] > 0" in out
    assert ("Enforce the z-Selector Format='Format' report-level filter across every "
            "Report report.") in out
    assert "Check: scan only; exit 1 if any report lacks the filter." in out
    assert "Fix: add or repair the filter on every report under PATH." in out
    assert ("pbi-plot-styler check --rule stale-placeholders --fix — repoint a saved "
            "blank-dimension binding") in out

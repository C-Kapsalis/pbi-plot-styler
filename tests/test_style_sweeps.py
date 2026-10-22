"""``style`` over folders, page folders and visual files; table patterns; output."""
from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from pbi_plot_styler.cli import main
from pbi_plot_styler.config import StylerConfig
from pbi_plot_styler.report import restyle_visual

from conftest import EXPECTED_KEYS


def _run(*args):
    return CliRunner().invoke(main, [str(a) for a in args])


def _visual(report: Path, page: str, vid: str) -> dict:
    return json.loads((report / "definition" / "pages" / page / "visuals" / vid / "visual.json")
                      .read_text(encoding="utf-8"))


def _meta(entries) -> list[str]:
    return [e["selector"]["metadata"] for e in entries if "metadata" in (e.get("selector") or {})]


def _bind_to_dataset(report: Path) -> None:
    (report / "definition.pbir").write_text(json.dumps({
        "version": "1.0", "datasetReference": {"byConnection": {"connectionString": "x"}}}),
        encoding="utf-8")


def _workspace(tmp_path: Path, project: Path, brewbar: Path) -> Path:
    root = tmp_path / "workspace"
    root.mkdir()
    project.rename(root / "roastery")
    brewbar.rename(root / "brewbar")
    return root


# -- SC8: a sweep skips a report it cannot pair with a model ---------------------
def test_a_sweep_skips_a_report_bound_to_a_published_dataset(tmp_path, project, brewbar):
    root = _workspace(tmp_path, project, brewbar)
    _bind_to_dataset(root / "brewbar" / "Brewbar.Report")
    result = _run(root)
    assert result.exit_code == 0, result.output
    assert "SKIPPED - no paired SemanticModel" in result.output
    assert "(1 skipped)" in result.output
    styled = _visual(root / "roastery" / "Roastery.Report", "monthlyperformance", "combo01")
    assert _meta(styled["visual"]["objects"]["dataPoint"]) == EXPECTED_KEYS


def test_a_sweep_skips_a_report_whose_model_styles_nothing(tmp_path, project, brewbar):
    root = _workspace(tmp_path, project, brewbar)
    # only the brewbar model has this field parameter
    result = _run(root, "--table", "Bar Metrics")
    assert result.exit_code == 0, result.output
    assert "SKIPPED - no paired SemanticModel" in result.output
    assert "(2 skipped)" in result.output


def test_a_single_report_bound_to_a_dataset_keeps_the_fatal_error(report_dir):
    # BUGFIX: a single report keeps the fatal error; only a sweep skips.
    _bind_to_dataset(report_dir)
    result = _run(report_dir)
    assert result.exit_code == 2, result.output
    assert "SKIPPED" not in result.output
    assert "--model" in result.output


def test_a_sweep_with_model_keeps_the_fatal_error(tmp_path, project, brewbar):
    root = _workspace(tmp_path, project, brewbar)
    result = _run(root, "--model", root / "roastery" / "Roastery.SemanticModel", "--table", "Bar Metrics")
    assert result.exit_code == 2


# -- SC23: table name patterns ------------------------------------------------------
def test_a_table_pattern_matches_case_insensitively(brewbar_report):
    result = _run(brewbar_report, "--table", "BAR MET*")
    assert result.exit_code == 0, result.output
    styled = _visual(brewbar_report, "overview", "combo10")
    assert sorted(set(_meta(styled["visual"]["objects"]["dataPoint"]))) == [
        "Sales Measures.Orders #", "Sales Measures.Revenue"]


def test_a_pattern_that_matches_nothing_is_not_an_error_by_itself(report_dir):
    result = _run(report_dir, "--table", "q-*", "--table", "y-*")
    assert result.exit_code == 0, result.output
    styled = _visual(report_dir, "monthlyperformance", "combo01")
    assert _meta(styled["visual"]["objects"]["dataPoint"]) == EXPECTED_KEYS


def test_a_table_pattern_in_the_config_file(report_dir, tmp_path):
    config = tmp_path / "plotstyler.toml"
    config.write_text('[tables]\nfield_parameters = ["y-plot specific"]\n', encoding="utf-8")
    assert _run(report_dir, "--config", config).exit_code == 2  # a plain name is matched exactly
    config.write_text('[tables]\nfield_parameters = ["y-plot [s]pecific"]\n', encoding="utf-8")
    result = _run(report_dir, "--config", config)
    assert result.exit_code == 0, result.output


# -- SC43: per-visual detail and totals ---------------------------------------------
def test_style_prints_entry_counts_exclusions_and_totals(brewbar_report):
    result = _run(brewbar_report, "--exclude-role", "Y")
    assert result.exit_code == 0, result.output
    line = next(ln for ln in result.output.splitlines() if "combo10" in ln)
    assert "dataPoint 5 -> 6, labels 3 -> 5" in line
    assert "2 columns-role measure(s) excluded" in line
    assert "rebuilt 1/1 combo chart(s)." in result.output


# -- SC44: seed a transparency without overwriting ----------------------------------
def _labels(report: Path) -> dict[str, dict]:
    data = json.loads((report / "definition/pages/overview/visuals/combo10/visual.json")
                      .read_text(encoding="utf-8"))
    return {e["selector"]["metadata"]: e["properties"] for e in data["visual"]["objects"]["labels"]
            if "metadata" in (e.get("selector") or {})}


def test_seed_label_transparency_fills_only_missing_values(brewbar_report):
    result = _run(brewbar_report, "--seed-label-transparency", "35")
    assert result.exit_code == 0, result.output
    labels = _labels(brewbar_report)
    assert labels["Sales Measures.Avg Ticket"]["backgroundTransparency"] == {"expr": {"Literal": {"Value": "35L"}}}
    assert labels["Sales Measures.Margin %"]["backgroundTransparency"] == {"expr": {"Literal": {"Value": "30L"}}}


def test_seed_and_enforced_transparency_together_are_rejected(brewbar_report):
    assert _run(brewbar_report, "--seed-label-transparency", "35", "--label-transparency", "10").exit_code == 2


# -- SC45: duplicates merge from the last occurrence ---------------------------------
def test_duplicate_entries_merge_from_the_last_one():
    key = "Sales Measures.Revenue"
    lit = lambda v: {"expr": {"Literal": {"Value": v}}}  # noqa: E731
    visual = {"visual": {"visualType": "lineClusteredColumnComboChart", "objects": {"dataPoint": [
        {"properties": {"fillTransparency": lit("15L")}, "selector": {"metadata": key}},
        {"properties": {"fillTransparency": lit("40L")}, "selector": {"metadata": key}},
    ]}}}
    out = restyle_visual(visual, [key], StylerConfig())
    entries = [e for e in out["visual"]["objects"]["dataPoint"] if e["selector"]["metadata"] == key]
    assert len(entries) == 1
    assert entries[0]["properties"]["fillTransparency"] == lit("40L")


# -- SC47: a page folder or a visual file -------------------------------------------
def test_style_a_page_folder_restyles_only_its_visuals(report_dir):
    page = report_dir / "definition" / "pages" / "monthlyperformance"
    other = report_dir / "definition" / "pages" / "seasonaltrends" / "visuals" / "combo02" / "visual.json"
    before = other.read_bytes()
    result = _run(page)
    assert result.exit_code == 0, result.output
    assert "rebuilt 1/1 combo chart(s)." in result.output
    assert other.read_bytes() == before
    assert _meta(_visual(report_dir, "monthlyperformance", "combo01")["visual"]["objects"]["dataPoint"]) \
        == EXPECTED_KEYS


def test_style_a_visual_file(report_dir):
    target = report_dir / "definition" / "pages" / "seasonaltrends" / "visuals" / "combo02" / "visual.json"
    other = report_dir / "definition" / "pages" / "monthlyperformance" / "visuals" / "combo01" / "visual.json"
    before = other.read_bytes()
    result = _run(target, "--dry-run")
    assert result.exit_code == 1, result.output
    assert "1/1 combo chart(s) need rebuild (re-run without --dry-run)." in result.output
    assert _run(target).exit_code == 0
    assert other.read_bytes() == before

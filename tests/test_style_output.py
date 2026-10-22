"""The console output of ``style``: the per-visual lines and the footer.

The tool prints what the earlier combo-line formatter printed: one line per
visual written (or one block per visual that would change in a dry run) and
a closing count. The lint framing of ``check`` does not apply here; the
lines below are the whole stdout of a run.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from pbi_plot_styler.cli import main

from cli_helpers import universal  # noqa: F401

REFERENCE_OPTIONS = ["--rebind-stale-line", "--theme-color-id", "9",
                     "--theme-color-percent", "0", "--table", "x-*"]


def _run(*args):
    return CliRunner().invoke(main, [str(a) for a in args])


def _combo(report: Path) -> Path:
    return (report / "definition" / "pages" / "a0b1c2d3e4f5a6b7c8d9" / "visuals"
            / "combo_main" / "visual.json")


def _rename_table(universal: Path, old: str, new: str) -> None:
    """Rename a table in the model and in every file that names it.

    The TMDL writes the apostrophe of the new name doubled; the visual
    files name the table as it is.
    """
    model = universal / "Performance.SemanticModel" / "definition" / "tables"
    path = model / f"{old}.tmdl"
    escaped = new.replace("'", "''")
    path.write_text(path.read_text(encoding="utf-8")
                    .replace(f"'{old}'", f"'{escaped}'"), encoding="utf-8")
    for other in model.glob("*.tmdl"):
        if other == path:
            continue
        text = other.read_text(encoding="utf-8")
        if f"'{old}'" in text:
            other.write_text(text.replace(f"'{old}'", f"'{escaped}'"), encoding="utf-8")
    for visual in (universal / "-Report.Report").rglob("visual.json"):
        text = visual.read_text(encoding="utf-8")
        if old in text:
            visual.write_text(text.replace(old, new), encoding="utf-8")


# -- SCX35: the per-visual result line ------------------------------------------
def test_a_written_visual_prints_its_counts(universal):
    report = universal / "-Report.Report"
    result = _run("style", report, *REFERENCE_OPTIONS)
    assert result.exit_code == 0, result.stdout
    line = next(ln for ln in result.stdout.splitlines() if ln.startswith("  combo_main: dataPoint"))
    assert "dataPoint 1 -> 2, labels 0 -> 2" in line
    assert "1 line measures each" in line
    assert "1 columns-role measure(s) excluded" in line
    assert "bar-side entr" in line and "preserved)" in line


def test_a_visual_that_is_not_written_prints_no_result_line(universal):
    report = universal / "-Report.Report"
    assert _run("style", report, *REFERENCE_OPTIONS).exit_code == 0
    again = _run("style", report, *REFERENCE_OPTIONS)
    assert again.exit_code == 0, again.output
    assert "dataPoint" not in again.output


# -- SCX36: the rebind line ------------------------------------------------------
def test_a_rebind_prints_the_rebound_line(universal):
    report = universal / "-Report.Report"
    result = _run("style", report, *REFERENCE_OPTIONS)
    assert result.exit_code == 0, result.stdout
    assert "  combo_main: Y2 rebound  '#Report Measures'.'!Cost'  ->  " \
           "'#Report Measures'.'Cost'" in result.stdout


def test_a_rebind_prints_the_stale_line_in_a_dry_run(universal):
    report = universal / "-Report.Report"
    result = _run("style", report, *REFERENCE_OPTIONS, "--dry-run")
    assert result.exit_code == 1, result.stdout
    assert "    Y2 stale: '#Report Measures'.'!Cost' -> would rebind to 'Cost'" \
        in result.stdout


def test_an_entity_with_an_apostrophe_is_double_quoted(universal):
    _rename_table(universal, "#Report Measures", "Client's Measures")
    result = _run("style", universal / "-Report.Report", *REFERENCE_OPTIONS)
    assert result.exit_code == 0, result.stdout
    assert '"Client\'s Measures"' in result.stdout


# -- SCX37: the dry-run block ----------------------------------------------------
def test_a_dry_run_prints_the_block_of_every_changed_visual(universal):
    report = universal / "-Report.Report"
    result = _run("style", report, *REFERENCE_OPTIONS, "--dry-run")
    assert result.exit_code == 1, result.stdout
    assert "  combo_main: WOULD CHANGE" in result.stdout
    assert "    objects.dataPoint[]: 1 -> 2 entries" in result.stdout
    assert "    objects.labels[]: 0 -> 2 entries" in result.stdout
    assert "--- " not in result.stdout  # no diff


def test_the_columns_role_line_lists_the_column_measures(project, report_dir):
    result = _run("style", report_dir, "--dry-run")
    assert result.exit_code == 1, result.stdout
    assert "    columns-role measure(s) kept OUT of the line set: " \
           "Sales Measures.Bags Sold #" in result.stdout


# -- SCX38: the closing lines ----------------------------------------------------
def test_the_footer_names_the_models_and_the_counts(project, report_dir):
    result = _run("style", report_dir)
    assert result.exit_code == 0, result.stdout
    assert result.stdout.endswith("\nModels resolved: 1\nrebuilt 2/2 combo chart(s).\n")


def test_a_second_run_says_everything_is_in_sync(project, report_dir):
    assert _run("style", report_dir).exit_code == 0
    again = _run("style", report_dir, "--dry-run")
    assert again.exit_code == 0, again.output
    assert again.output.endswith("\nModels resolved: 1\nAll 2 combo chart(s) already in sync.\n")


def test_a_dry_run_that_would_change_says_so(project, report_dir):
    result = _run("style", report_dir, "--dry-run")
    assert result.exit_code == 1, result.stdout
    assert result.stdout.endswith(
        "\nModels resolved: 1\n2/2 combo chart(s) need rebuild "
        "(re-run without --dry-run).\n")


# -- SCX39: a report without a usable model ---------------------------------------
def test_a_report_without_a_model_is_skipped_one_line_per_visual(tmp_path, project, brewbar):
    root = tmp_path / "workspace"
    root.mkdir()
    project.rename(root / "roastery")
    brewbar.rename(root / "brewbar")
    (root / "brewbar" / "Brewbar.Report" / "definition.pbir").write_text(
        json.dumps({"version": "1.0",
                    "datasetReference": {"byConnection": {"connectionString": "x"}}}),
        encoding="utf-8")
    result = _run("style", root)
    assert result.exit_code == 0, result.stdout
    skipped = [ln for ln in result.stdout.splitlines() if "SKIPPED" in ln]
    assert skipped, result.stdout
    for line in skipped:
        assert line == ("  combo10: SKIPPED - no paired SemanticModel "
                        "(missing definition.pbir / no x-Selector measures)"), line
    assert "(1 skipped)" in result.stdout


# -- SCX40: the lines the original never prints -----------------------------------
def test_the_run_prints_no_other_lines(project, report_dir):
    result = _run("style", report_dir)
    assert result.exit_code == 0, result.stdout
    for line in result.stdout.splitlines():
        assert not line.startswith("Report:"), line
        assert not line.startswith("Model:"), line
        assert not line.startswith("Measures:"), line
        assert not line.startswith("  styled"), line


# -- SCX41: a path that does not exist --------------------------------------------
def test_a_path_that_does_not_exist(tmp_path):
    missing = tmp_path / "nope"
    result = _run("style", missing)
    assert result.exit_code == 2
    assert result.stderr == f"ERROR: {missing.resolve()} does not exist\n"
    assert result.stdout == ""


# -- SCX42: a visual file that cannot be read --------------------------------------
def test_a_visual_file_that_does_not_parse(tmp_path, project, report_dir):
    target = report_dir / "definition" / "pages" / "seasonaltrends" / "visuals" \
        / "combo02" / "visual.json"
    target.write_text("{not json", encoding="utf-8")
    result = _run("style", target)
    assert result.exit_code == 2
    assert result.stderr.startswith(f"  ERROR reading {target.resolve()}: "), result.stderr
    assert "already in sync" not in result.stdout

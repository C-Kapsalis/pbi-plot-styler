"""Regression tests for the bugs found in the 1.2.1 audit.

Each test reproduces one bug on the coffee-roastery example or a test
fixture, through the public command line only.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from pbi_plot_styler.cli import main

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "examples" / "coffee-roastery"
FIXTURES = Path(__file__).parent / "fixtures"
COMBO = "5dd25eb672a72da45096"


def _run(*args):
    return CliRunner().invoke(main, [str(a) for a in args])


@pytest.fixture
def roastery(tmp_path: Path) -> Path:
    """A writable copy of the coffee-roastery example, without its config."""
    dest = tmp_path / "coffee-roastery"
    shutil.copytree(EXAMPLE, dest)
    (dest / "plotstyler.toml").unlink()
    return dest


def _block(output: str, visual: str) -> list[str]:
    lines = output.splitlines()
    start = lines.index(f"  {visual}: WOULD CHANGE")
    block = []
    for line in lines[start + 1:]:
        if not line.startswith("    "):
            break
        block.append(line)
    return block


# -- 1: the dry run names the column measures the write run really excludes ------
def test_the_dry_run_does_not_claim_an_exclusion_the_write_run_skips(roastery):
    report = roastery / "Roastery.Report"
    dry = _run("style", report, "--dry-run")
    assert dry.exit_code == 1, dry.output
    block = _block(dry.output, COMBO)
    assert not any("kept OUT" in line for line in block), block
    assert "    objects.dataPoint[]: 0 -> 6 entries" in block
    wrote = _run("style", report)
    assert wrote.exit_code == 0, wrote.output
    assert "dataPoint 0 -> 6" in wrote.output
    assert "0 columns-role measure(s) excluded" in wrote.output


def test_the_dry_run_names_an_excluded_role_measure(roastery):
    report = roastery / "Roastery.Report"
    dry = _run("style", report, "--dry-run", "--exclude-role", "Y")
    block = _block(dry.output, COMBO)
    assert ("    columns-role measure(s) kept OUT of the line set: "
            "Sales Measures.Revenue") in block
    assert "    objects.dataPoint[]: 0 -> 5 entries" in block
    wrote = _run("style", report, "--exclude-role", "Y")
    assert "dataPoint 0 -> 5" in wrote.output
    assert "1 columns-role measure(s) excluded" in wrote.output


# -- 2: a relative page folder or visual.json styles the visuals under it --------
PAGE = "Roastery.Report/definition/pages/a1f935c9ad3918c55c49"


@pytest.mark.parametrize("scope", [PAGE, f"{PAGE}/visuals/{COMBO}/visual.json"],
                         ids=["page-folder", "visual-file"])
def test_a_relative_scope_path_styles_its_visuals(roastery, monkeypatch, scope):
    monkeypatch.chdir(roastery)
    result = _run("style", scope, "--dry-run")
    assert result.exit_code == 1, result.output
    assert f"  {COMBO}: WOULD CHANGE" in result.output


def test_the_current_page_folder_styles_its_visuals(roastery, monkeypatch):
    monkeypatch.chdir(roastery / PAGE)
    result = _run("style", ".", "--dry-run")
    assert result.exit_code == 1, result.output
    assert f"  {COMBO}: WOULD CHANGE" in result.output


# -- 3: a single report or --model without a usable model is a fatal error --------
def _break_model(roastery: Path, how: str) -> None:
    if how == "no-pbir":
        (roastery / "Roastery.Report" / "definition.pbir").unlink()
    elif how == "no-model":
        shutil.rmtree(roastery / "Roastery.SemanticModel")
    elif how == "no-tables":
        shutil.rmtree(roastery / "Roastery.SemanticModel" / "definition" / "tables")


@pytest.mark.parametrize("how", ["no-pbir", "no-model", "no-tables"])
@pytest.mark.parametrize("dry_run", [False, True], ids=["write", "dry-run"])
def test_a_single_report_without_a_usable_model_fails(roastery, how, dry_run):
    _break_model(roastery, how)
    result = _run("style", roastery / "Roastery.Report", *(["--dry-run"] if dry_run else []))
    assert result.exit_code == 2, result.output
    assert "SKIPPED" not in result.output
    assert "already in sync" not in result.output
    assert "Error:" in result.output


def test_model_without_tables_fails_even_for_a_sweep(roastery):
    _break_model(roastery, "no-tables")
    result = _run("style", roastery, "--model", roastery / "Roastery.SemanticModel")
    assert result.exit_code == 2, result.output
    assert "SKIPPED" not in result.output


def test_a_sweep_still_skips_a_report_without_a_model(roastery, tmp_path):
    other = tmp_path / "coffee-roastery" / "second"
    other.mkdir()
    shutil.copytree(roastery / "Roastery.Report", other / "Second.Report")
    (other / "Second.Report" / "definition.pbir").unlink()
    result = _run("style", roastery, "--dry-run")
    assert result.exit_code == 1, result.output
    assert f"  {COMBO}: SKIPPED - no paired SemanticModel" in result.output
    assert "(1 skipped)" in result.output


# -- 4: the slicer-mode-gates fix reports what it wrote ---------------------------
def _digest(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in sorted(root.rglob("*")) if p.is_file()}


def test_the_mode_gate_fix_counts_the_files_and_references_it_patched(tmp_path):
    root = tmp_path / "mode-gates"
    shutil.copytree(FIXTURES / "mode-gates", root)
    before = _digest(root)
    result = _run("check", root / "-Canvas.Report", "--rule", "slicer-mode-gates", "--fix")
    after = _digest(root)
    changed = sorted(k for k in before if before[k] != after[k])
    assert len(changed) == 3, changed
    out = result.stdout
    # two slicer visuals get their gate; the bookmark keeps its entries but
    # its two stale gate references are repointed
    assert "  Patched 2 visual(s) and 0 bookmark entries across 2 file(s)" in out
    assert "  Patched 2 stale entity reference(s) -> 'f-Filters' across 1 file(s)" in out
    again = _run("check", root / "-Canvas.Report", "--rule", "slicer-mode-gates", "--fix")
    assert "  Patched 0 visual(s) and 0 bookmark entries across 0 file(s)" in again.stdout
    assert ("  Patched 0 stale entity reference(s) -> 'f-Filters' across 0 file(s)"
            in again.stdout)


def test_the_mode_gate_check_spells_entries(tmp_path):
    root = tmp_path / "mode-gates"
    shutil.copytree(FIXTURES / "mode-gates", root)
    out = _run("check", root / "-Canvas.Report", "--rule", "slicer-mode-gates").stdout
    assert "  Would patch 2 visual(s) and 0 bookmark entries" in out
    assert "entrie(s)" not in out


# -- 5: the help, the docs and the explicit field-parameter line ------------------
def _option_help(command: str, option: str) -> str:
    """The help text of one option, joined onto one line."""
    out = _run(command, "--help").output
    lines = out.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.strip().startswith(option))
    text = [lines[start].strip()]
    for line in lines[start + 1:]:
        if line.strip().startswith("-") or not line.strip():
            break
        text.append(line.strip())
    return " ".join(text)


def test_the_style_dry_run_help_describes_the_block_not_a_diff():
    text = _option_help("style", "--dry-run")
    assert "diff" not in text, text
    assert "WOULD CHANGE" in text, text


@pytest.mark.parametrize("option", ["--table", "--rename-table"])
def test_the_table_options_describe_the_detection(option):
    text = _option_help("style", option)
    assert "trio" not in text, text
    assert "detected" in text, text


def test_an_explicit_list_prints_its_field_parameter_line(roastery):
    result = _run("style", roastery / "Roastery.Report", "--dry-run",
                  "--table", "x-Plot Specific 2")
    lines = result.output.splitlines()
    assert lines[0] == "Field parameters: x-Plot Specific 2 (explicit)", result.output


def test_the_commands_doc_gives_the_self_test_output_the_right_way_round():
    doc = " ".join((ROOT / "docs" / "commands.md").read_text(encoding="utf-8").split())
    assert "the legacy layout prints `self-test PASS` only" in doc, doc
    assert "(the legacy layout adds" not in doc


# -- 6: THM006 names only the missing theme and gives the right remedy -------------
def test_the_thm006_violation_line_names_only_the_missing_theme(roastery):
    # the example declares a baseTheme but no customTheme
    out = _run("check", roastery / "Roastery.Report", "--rule", "theme").stdout
    violations = [ln for ln in out.splitlines() if ln.startswith("   \U0001F534 ")]
    assert violations == [
        "   \U0001F534 report: Theme collection is incomplete - missing: customTheme. "
        "Reports must declare both baseTheme and customTheme."], out


def test_the_thm006_hint_says_to_declare_the_theme():
    from pbi_plot_styler.rules import fix_hint

    hint = fix_hint("THM006")
    assert "themeCollection" in hint and "report.json" in hint, hint
    assert "restore the missing theme file" not in hint


# -- 7: minor output fixes ----------------------------------------------------------
def test_a_non_compliant_rule_block_carries_a_cross(roastery):
    out = _run("check", roastery / "Roastery.Report", "--rule", "theme").stdout
    assert "❌ Rule #6 Validation Results:" in out, out
    assert "✅ Rule #6" not in out
    clean = _run("check", roastery / "Roastery.Report", "--rule", "category-filter").stdout
    assert "✅ Rule #3 Validation Results:" in clean, clean


def test_the_format_selector_fix_prints_its_patched_line_once(tmp_path):
    import json

    root = tmp_path / "universal"
    shutil.copytree(FIXTURES / "universal", root)
    report_json = root / "-Report.Report" / "definition" / "report.json"
    data = json.loads(report_json.read_text(encoding="utf-8"))
    data.pop("filterConfig", None)
    report_json.write_text(json.dumps(data, indent=2), encoding="utf-8")
    out = _run("check", root / "-Report.Report", "--rule", "format-selector", "--fix").stdout
    patched = [ln for ln in out.splitlines() if "patched (" in ln]
    assert len(patched) == 1, out
    assert "Patched 1/1 report(s)." in out


def test_an_empty_parameter_kind_reads_none(roastery):
    tables = roastery / "Roastery.SemanticModel" / "definition" / "tables"
    (tables / "y-Plot Specific.tmdl").unlink()  # the only dimension parameter
    out = _run("style", roastery / "Roastery.Report", "--dry-run").output
    line = out.splitlines()[0]
    assert line == ("Field parameters: x-Plot Specific 1, x-Plot Specific 2 "
                    "(dimension: none; metric: x-Plot Specific 1, x-Plot Specific 2)"), out


def test_thm004_counts_a_dax_colour_literal(roastery):
    import json

    report_json = roastery / "Roastery.Report" / "definition" / "report.json"
    data = json.loads(report_json.read_text(encoding="utf-8"))
    data.setdefault("objects", {})["outspacePane"] = [{"properties": {"backgroundColor": {
        "solid": {"color": {"expr": {"Literal": {"Value": "'#FF0000'"}}}}}}}]
    report_json.write_text(json.dumps(data, indent=2), encoding="utf-8")
    out = _run("check", roastery / "Roastery.Report", "--rule", "theme").stdout
    assert "THM004" in out, out
    assert "1 hard-coded hex color literal(s) in report.json (sample: \"'#FF0000'\")" in out

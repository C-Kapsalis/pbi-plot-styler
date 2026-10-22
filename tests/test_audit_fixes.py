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

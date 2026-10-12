"""Shared fixtures: a disposable copy of the fictional roastery project."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "roastery"

#: Sorted "Table.Measure" keys the roastery field parameters expose.
EXPECTED_KEYS = [
    "Quality Measures.Avg Cupping Score",
    "Sales Measures.Bags Sold #",
    "Sales Measures.Revenue",
    "Sales Measures.Sample Requests #",
    "Sales Measures.Wholesale Margin %",
]


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A writable copy of the roastery PBIP project."""
    dest = tmp_path / "roastery"
    shutil.copytree(FIXTURES_DIR, dest)
    return dest


@pytest.fixture
def report_dir(project: Path) -> Path:
    return project / "Roastery.Report"


@pytest.fixture
def model_dir(project: Path) -> Path:
    return project / "Roastery.SemanticModel"


BREWBAR_DIR = Path(__file__).parent / "fixtures" / "brewbar"


@pytest.fixture
def brewbar(tmp_path: Path) -> Path:
    """A writable copy of the brewbar project (hand-tuned formatting,
    bookmarks, a columns role bound through a field parameter)."""
    dest = tmp_path / "brewbar"
    shutil.copytree(BREWBAR_DIR, dest)
    return dest


@pytest.fixture
def brewbar_report(brewbar: Path) -> Path:
    return brewbar / "Brewbar.Report"

"""Shared helpers for the report-architecture tests.

They drive pbi-plot-styler through its public surface only:

* the ``check`` command with ``--rule <slug>`` (one rule at a time),
  ``--config <plotstyler.toml>``, ``--json``, ``--fix``, ``--baseline`` and
  ``--update-baseline``;
* the ``check --summary`` overview;
* the ``style --rebind-stale-line`` option;
* the ``bookmarks build`` command;
* the ``pbi_plot_styler.rename`` Python module.

Every new finding id lives in ``IDS`` below, so renaming an id is a one-line
change. The rule slugs live in ``RULES``.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Iterable

import pytest
from click.testing import CliRunner

from pbi_plot_styler.cli import main

FIXTURES = Path(__file__).parent / "fixtures"
BASELINES = Path(__file__).parent / "baselines"

#: ``--rule`` slug per spec.
RULES = {
    "answer-bookmarks": "answer-bookmarks",        # F-answer-bookmark-* + F-canvas-page-wells P1/P2
    "bookmark-literals": "bookmark-literals",      # F-bookmark-picker-literals
    "category-filter": "category-filter",          # F-canvas-category-filter (foundation rule 3)
    "slicer-gates": "slicer-gates",                # F-slicer-gate-filter (foundation rule 1)
    "slicer-mode-gates": "slicer-mode-gates",      # F-slicer-mode-gates
    "theme": "theme",                              # F-theme-integration (foundation rule 6)
    "visual-position": "visual-position",          # F-visual-position-present
    "y-combo": "y-combo",                          # F-y-combo-group-naming
    "filter-panel": "filter-panel",                # F-filter-panel-master-group (foundation rule 8)
    "format-selector": "format-selector",          # F-format-selector-filter
    "stale-placeholders": "stale-placeholders",    # F-stale-placeholder-bindings
}

#: Proposed finding ids (spec check name -> id).
IDS = {
    # F-answer-bookmark-suite / -matrix-capture / -registration-and-filters / -slot-map
    "vacuity": "ABK000",
    "T1": "ABK001",
    "T3": "ABK003",
    "T4": "ABK004",
    "T5": "ABK005",
    "T6": "ABK006",
    "T7": "ABK007",
    "T8": "ABK008",
    "T9": "ABK009",
    "T10": "ABK010",
    # F-canvas-page-wells (P3 is the existing FPM001 / FPM002)
    "P1": "PGW001",
    "P2": "PGW002",
    "P3-overlap": "FPM001",
    "P3-range": "FPM002",
    # F-bookmark-picker-literals
    "LIT-elsewhere": "BML001",
    "LIT-unregistered": "BML002",
    # F-canvas-category-filter
    "RULE3": "CAT001",
    # F-slicer-gate-filter
    "RULE1-visual": "GAT001",
    "RULE1-bookmark": "GAT002",
    # F-slicer-mode-gates
    "MODE-gate": "GAT003",          # absent / passive gate for the slicer's mode
    "MODE-wrong-entity": "GAT004",  # active gate bound to a table that does not declare it
    "MODE-stale-ref": "GAT005",     # stale gate entity reference (normalisation)
    # F-theme-integration
    "THEME-NONE": "THM002",
    "THEME-CUSTOM-MISSING": "THM003",
    "THEME-HEX": "THM004",
    "THEME-ANY": "THM005",
    "THEME-BOTH": "THM006",
    # F-visual-position-present
    "POSITION": "POS001",
    # F-y-combo-group-naming
    "YCOMBO-name": "YCG001",
    "YCOMBO-orphan": "YCG002",
    # F-filter-panel-master-group
    "RULE8-missing": "PNL001",
    "RULE8-not-group": "PNL002",
    # F-format-selector-filter
    "FORMAT": "FMT001",
    # F-stale-placeholder-bindings
    "STALE": "PLH001",
}

#: Exit codes of the check command (unchanged from 1.1.0).
EXIT_OK, EXIT_FINDINGS, EXIT_USAGE = 0, 1, 2


def run(*args: Any) -> Any:
    """Invoke the styler CLI in-process; returns the click Result."""
    return CliRunner().invoke(main, [str(a) for a in args], catch_exceptions=False)


def check_json(path: Path, rule: str, *extra: Any, config: Path | None = None) -> dict:
    """``check PATH --rule RULE --json [--config C] [extra...]`` as a dict."""
    args: list[Any] = ["check", path, "--rule", RULES[rule], "--json"]
    if config is not None:
        args += ["--config", config]
    result = run(*args, *extra)
    try:
        payload = json.loads(result.output)
    except json.JSONDecodeError:
        pytest.fail(f"check did not print JSON (exit {result.exit_code}):\n{result.output}")
    assert payload["exit_code"] == result.exit_code, result.output
    return payload


def ids(payload: dict, *, new_only: bool = False) -> list[str]:
    return sorted(
        f["id"] for f in payload["findings"] if not (new_only and f.get("baselined"))
    )


def of(payload: dict, key: str, *, new_only: bool = False) -> list[dict]:
    """Findings with the id mapped from ``key`` (see ``IDS``)."""
    want = IDS[key]
    return [
        f for f in payload["findings"]
        if f["id"] == want and not (new_only and f.get("baselined"))
    ]


def errors(payload: dict) -> list[dict]:
    return [f for f in payload["findings"] if f["severity"] == "error"]


def copy_fixture(name: str, dest: Path) -> Path:
    """Copy ``tests/fixtures/<name>`` to ``dest/<basename>`` and return it."""
    src = FIXTURES / name
    target = dest / Path(name).name
    shutil.copytree(src, target)
    return target


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def edit_json(path: Path, mutate) -> None:
    data = load(path)
    mutate(data)
    dump(path, data)


def write_toml(path: Path, sections: dict[str, dict[str, Any]]) -> Path:
    """Write a small plotstyler.toml (strings, ints, bools, lists, inline maps)."""

    def value(v: Any) -> str:
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, (int, float)):
            return repr(v)
        if isinstance(v, str):
            return json.dumps(v)
        if isinstance(v, (list, tuple)):
            return "[" + ", ".join(value(x) for x in v) + "]"
        if isinstance(v, dict):
            return "{" + ", ".join(f"{json.dumps(k)} = {value(x)}" for k, x in v.items()) + "}"
        raise TypeError(v)

    lines: list[str] = []
    for section, keys in sections.items():
        lines.append(f"[{section}]")
        lines += [f"{k} = {value(v)}" for k, v in keys.items()]
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def visual_files(report: Path) -> Iterable[Path]:
    return sorted((report / "definition" / "pages").glob("*/visuals/*/visual.json"))


# -- report discovery (F-canvas-config) ---------------------------------------
#: The sample client: tests/fixtures/universal holds
#: Performance.SemanticModel, -Report.Report (deliverable) and M.Report
#: (API-only, excluded from default sweeps).
UNIVERSAL = "universal"


@pytest.fixture
def universal(tmp_path: Path) -> Path:
    """A writable copy of the sample client folder."""
    return copy_fixture(UNIVERSAL, tmp_path)


@pytest.fixture
def report_context(universal: Path) -> Path:
    """The deliverable report of the sample client (the styler discovers
    reports itself, so no per-report parser fixture is needed)."""
    return universal / "-Report.Report"

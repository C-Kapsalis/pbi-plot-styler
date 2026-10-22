"""SC23 (owner's decision) at the command level.

- With no config, the field-parameter set is DETECTED from the model, so a
  parameter whose name is not an `x-` one is in the set.
- With an explicit list, only the listed tables are in the set.
- `--exclude-role` still drops the whole catalog of a detected parameter,
  even one the user did not configure.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from pbi_plot_styler.cli import main

PARAM_META = """
		extendedProperty ParameterMetadata =
				{
				  "version": 3,
				  "kind": 2
				}
"""


def _run(*args):
    return CliRunner().invoke(main, [str(a) for a in args])


def _add_parameter(model: Path, name: str, measure: str) -> None:
    """A metric field parameter with a name that is not an `x-` one."""
    path = model / "definition" / "tables" / f"{name}.tmdl"
    path.write_text(
        f"table '{name}'\n"
        "\tlineageTag: 00000000-0000-4000-8000-000000000900\n\n"
        f"\tcolumn '{name}'\n"
        "\t\tlineageTag: 00000000-0000-4000-8000-000000000901\n"
        "\t\tsummarizeBy: none\n"
        "\t\tsourceColumn: [Value1]\n"
        f"{PARAM_META}"
        f"\tpartition '{name}' = calculated\n"
        "\t\tmode: import\n"
        "\t\tsource =\n"
        "\t\t\t\t{\n"
        f"\t\t\t\t    ( \"Revenue\", NAMEOF ( 'Sales Measures'[Revenue] ), 1, \"c\" )\n"
        "\t\t\t\t}\n",
        encoding="utf-8")


def test_the_detected_tables_are_printed(project, report_dir, model_dir):
    """One line names the detected tables."""
    _add_parameter(model_dir, "Bar Metrics", "Revenue")
    result = _run(report_dir)
    assert result.exit_code in (0, 2), result.output
    line = next((ln for ln in result.output.splitlines()
                 if ln.startswith("Field parameters:")), None)
    assert line, result.output
    assert "Bar Metrics" in line, line


def test_a_detected_parameter_with_a_non_x_name_is_in_the_set(project,
                                                              report_dir,
                                                              model_dir):
    """The detection is not a name pattern."""
    _add_parameter(model_dir, "Bar Metrics", "Revenue")
    result = _run(report_dir)
    line = next((ln for ln in result.output.splitlines()
                 if ln.startswith("Field parameters:")), None)
    assert line and "Bar Metrics" in line, result.output


def test_an_explicit_list_restricts_the_set(project, report_dir, tmp_path):
    """With `--table`, only the listed tables are used."""
    _add_parameter(project / "Roastery.SemanticModel", "Bar Metrics",
                   "Revenue")
    config = tmp_path / "plotstyler.toml"
    config.write_text('[tables]\nfield_parameters = ["x-Plot Specific 1"]\n',
                      encoding="utf-8")
    result = _run(report_dir, "--config", config)
    assert result.exit_code in (0, 2), result.output
    line = next((ln for ln in result.output.splitlines()
                 if ln.startswith("Field parameters:")), None)
    assert line is None or "Bar Metrics" not in line, result.output

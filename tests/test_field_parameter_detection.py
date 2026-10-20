"""SC23 (owner's decision): the field parameters are detected from the model.

The field-parameter set is the explicit `--table` / config list when the
user gives one. Otherwise the tool detects the model's field parameters
from the TMDL: a calculated table whose column carries
`extendedProperty ParameterMetadata` and whose rows are `NAMEOF(...)`
tuples. Name patterns only rank or label the detected tables; they never
replace the detection.

Each detected parameter is classified by what its `NAMEOF` rows point at:
columns make a dimension parameter, measures make a metric parameter, and
a mix is flagged. The measures the styling drives come from the metric
parameters; the column wells and the excluded roles work on the whole
detected set, so a Y role bound through a parameter the user did not
configure still excludes that parameter's whole catalog.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pbi_plot_styler.fieldparams import detect_field_parameters

PARAM_META = """
		extendedProperty ParameterMetadata =
				{
				  "version": 3,
				  "kind": 2
				}
"""


def _table(name: str, rows: str, *, parameter: bool = True) -> str:
    meta = PARAM_META if parameter else ""
    return (
        f"table '{name}'\n"
        "\tlineageTag: 00000000-0000-4000-8000-000000000010\n\n"
        f"\tcolumn '{name}'\n"
        "\t\tlineageTag: 00000000-0000-4000-8000-000000000011\n"
        "\t\tsummarizeBy: none\n"
        "\t\tsourceColumn: [Value1]\n"
        f"{meta}"
        "\tpartition '" + name + "' = calculated\n"
        "\t\tmode: import\n"
        "\t\tsource =\n"
        "\t\t\t\t{\n"
        f"{rows}"
        "\t\t\t\t}\n"
    )


def test_a_parameter_is_detected_whatever_its_name():
    """The name is a hint, not the rule."""
    tables = {"Bar Metrics": _table(
        "Bar Metrics",
        "\t\t\t\t    ( \"Revenue\", NAMEOF ( '#Report Measures'[Revenue] ), 1, \"c\" )\n")}
    found = detect_field_parameters(tables, {"#Report Measures": {"Revenue"}})
    assert found.names == ("Bar Metrics",), found.names


def test_a_table_without_the_metadata_is_not_a_parameter():
    """The metadata is what makes a field parameter."""
    tables = {"x-Selector 1": _table(
        "x-Selector 1",
        "\t\t\t\t    ( \"Region\", NAMEOF ( 'Sales'[Region] ), 1, \"c\" )\n",
        parameter=False)}
    found = detect_field_parameters(tables, {"Sales": set()})
    assert found.names == (), found.names


def test_a_parameter_is_classified_by_what_its_rows_point_at():
    """Columns make a dimension parameter; measures a metric one."""
    tables = {
        "x-Selector 1": _table(
            "x-Selector 1",
            "\t\t\t\t    ( \"Revenue\", NAMEOF ( '#Report Measures'[Revenue] ), 1, \"c\" )\n"),
        "y-Selector 1": _table(
            "y-Selector 1",
            "\t\t\t\t    ( \"Region\", NAMEOF ( 'Sales'[Region] ), 1, \"c\" )\n"),
    }
    found = detect_field_parameters(tables, {"#Report Measures": {"Revenue"},
                                             "Sales": set()})
    assert found.metric_names == ("x-Selector 1",), found.names
    assert found.dimension_names == ("y-Selector 1",), found.names

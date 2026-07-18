"""TMDL parsing: measure inventory and field-parameter reference resolution."""
from __future__ import annotations

import pytest

from pbi_plot_styler.config import DEFAULT_FIELD_PARAMETER_TABLES
from pbi_plot_styler.tmdl import SemanticModel, strip_dax_comments

from conftest import EXPECTED_KEYS


def test_measure_inventory(model_dir):
    model = SemanticModel.load(model_dir)
    assert model.measures_by_table["Sales Measures"] == {
        "Bags Sold #",
        "Revenue",
        "Cost of Goods",
        "Wholesale Margin %",
        "Sample Requests #",
        "Retired Blend Sales",
        "Legacy Subscriptions #",
    }
    assert model.measures_by_table["Quality Measures"] == {
        "Avg Cupping Score",
        "Defect Rate %",
    }
    # Dimension tables declare no measures.
    assert model.measures_by_table["Beans"] == set()


def test_field_parameter_measures_are_sorted_table_dot_measure_keys(model_dir):
    model = SemanticModel.load(model_dir)
    keys = model.field_parameter_measures(DEFAULT_FIELD_PARAMETER_TABLES)
    assert keys == EXPECTED_KEYS


def test_column_references_are_not_treated_as_measures(model_dir):
    """x-Plot tables reference only columns; none may leak into the keys."""
    model = SemanticModel.load(model_dir)
    keys = model.field_parameter_measures(DEFAULT_FIELD_PARAMETER_TABLES)
    assert not any("Origin Country" in k for k in keys)
    assert not any("Brew Method" in k for k in keys)
    assert not any("Grind" in k for k in keys)


def test_commented_out_tuples_are_ignored(model_dir):
    """Retired measures parked as -- / // comments never seed styling."""
    model = SemanticModel.load(model_dir)
    keys = model.field_parameter_measures(DEFAULT_FIELD_PARAMETER_TABLES)
    # Both are real measures in the model, but commented out in y-Plot Specific.
    assert "Sales Measures.Retired Blend Sales" not in keys
    assert "Sales Measures.Legacy Subscriptions #" not in keys


def test_missing_all_tables_raises(model_dir):
    model = SemanticModel.load(model_dir)
    with pytest.raises(LookupError):
        model.field_parameter_measures(("No Such Table",))


def test_strip_dax_comments_respects_strings():
    text = '( "a -- not a comment", NAMEOF ( [M] ), 1, "c" ), -- gone\n// all gone'
    stripped = strip_dax_comments(text)
    assert '"a -- not a comment"' in stripped
    assert "gone" not in stripped

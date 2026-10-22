"""Names with an apostrophe or a closing bracket inside written DAX literals."""
from __future__ import annotations

from pbi_plot_styler import qx
from pbi_plot_styler.bookmark_builder import _pick_literal
from pbi_plot_styler.rules.format_selector import _wanted


def test_a_quoted_string_doubles_its_apostrophes():
    assert qx.quoted("Rep's view") == "'Rep''s view'"
    assert qx.quoted("Plain") == "'Plain'"


def test_a_pick_literal_escapes_table_and_column():
    assert _pick_literal({"table": "#Report Measures", "column": "CPA"}) == \
        "'''#Report Measures''[CPA]'"
    assert _pick_literal({"table": "Rep's", "column": "A]B"}) == "'''Rep''''s''[A]]B]'"


def test_the_format_item_is_compared_in_its_escaped_form():
    assert _wanted("Rep's Format") == "'Rep''s Format'"


# -- reading escaped literals back -----------------------------------------------
def test_an_escaped_selection_literal_is_read_back_to_plain_names():
    from pbi_plot_styler.canvas import parse_selection

    assert parse_selection("'''#Report Measures''[CPA]'") == ("#Report Measures", "CPA")
    assert parse_selection(_pick_literal({"table": "Rep's", "column": "A]B"})) == ("Rep's", "A]B")
    assert parse_selection(_pick_literal({"table": "T", "column": "Rep's Spend"})) == \
        ("T", "Rep's Spend")


def test_selection_literals_are_found_anywhere_in_a_container():
    from pbi_plot_styler.canvas import selection_literals

    container = {"a": [{"Literal": {"Value": _pick_literal({"table": "T", "column": "A]B"})}}],
                 "b": {"Literal": {"Value": "'plain'"}}}
    assert selection_literals(container) == [("T", "A]B")]


def test_nameof_with_a_doubled_bracket_is_read_as_one_name(tmp_path):
    from pbi_plot_styler.tmdl import SemanticModel

    tables = tmp_path / "M.SemanticModel" / "definition" / "tables"
    tables.mkdir(parents=True)
    (tables / "x-Pick.tmdl").write_text(
        "table 'x-Pick'\n\n\tpartition 'x-Pick' = calculated\n\t\tsource = {\n"
        "\t\t\t(\"A]B\", NAMEOF('Rep''s'[A]]B]), 0)\n\t\t}\n",
        encoding="utf-8")
    refs = SemanticModel.load(tmp_path / "M.SemanticModel").nameof_refs("x-Pick")
    assert [(r.qualifier, r.name) for r in refs] == [("Rep's", "A]B")]

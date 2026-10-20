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

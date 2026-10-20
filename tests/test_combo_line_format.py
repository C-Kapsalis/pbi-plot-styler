"""Combo-chart line formatting over a whole client folder (imposed, not asserted).

Runs ``pbi-plot-styler style --rebind-stale-line`` (F-combo-line-format) on a
tmp copy of the sample client tests/fixtures/universal, whose combo chart has
a stale line projection ('#Report Measures'[!Cost], renamed to Cost in the
model) and a column-side measure (Clicks on Y), and expects exit 0 and a
second run that changes nothing.

The x-axis field-parameter tables are listed explicitly rather than matched
by a name pattern; the styler's default trio is not used here.
"""
from __future__ import annotations

import json

import pytest

from cli_helpers import report_context, run, universal  # noqa: F401

REFERENCE_OPTIONS = ["--rebind-stale-line", "--theme-color-id", "9", "--theme-color-percent", "0",
          "--table", "x-Selector 1", "--table", "x-Plot Specific 1", "--table", "x-Plot Specific 2"]


def _combo(client):
    return client / "-Report.Report" / "definition" / "pages" / "a0b1c2d3e4f5a6b7c8d9" / "visuals" / "combo_main" / "visual.json"


def _metadata_keys(entries):
    return [e.get("selector", {}).get("metadata") for e in entries if "metadata" in e.get("selector", {})]


@pytest.mark.layer3_5
@pytest.mark.visual_architecture
class TestComboLineFormat:

    @pytest.mark.p1
    def test_impose_combo_chart_format(self, universal):
        client_dir = universal
        result = run("style", client_dir, *REFERENCE_OPTIONS)
        assert result.exit_code == 0, result.output

        visual = json.loads(_combo(client_dir).read_text(encoding="utf-8"))["visual"]
        y2 = visual["query"]["queryState"]["Y2"]["projections"][0]
        assert y2["field"]["Measure"]["Property"] == "Cost"
        assert y2["queryRef"] == "#Report Measures.Cost"
        keys = _metadata_keys(visual["objects"]["dataPoint"])
        assert "#Report Measures.Cost" in keys
        assert "#Report Measures.Clicks" not in keys  # column side, never styled
        # the no-selector bar default is preserved verbatim
        assert visual["objects"]["dataPoint"][0] == {"properties": {"fill": {"solid": {"color": {
            "expr": {"ThemeDataColor": {"ColorId": 2, "Percent": 0}}}}}}}

        before = _combo(client_dir).read_bytes()
        again = run("style", client_dir, *REFERENCE_OPTIONS)
        assert again.exit_code == 0, again.output
        assert _combo(client_dir).read_bytes() == before  # a second run writes nothing

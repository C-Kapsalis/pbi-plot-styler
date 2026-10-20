"""Owned-entries-only merge: the styler rewrites only the formatting it owns.

Every expectation below is read from the brewbar fixture's ground truth (the
literal entries the fixture ships with), never from the styler's agreement
with itself.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from pbi_plot_styler.cli import main
from pbi_plot_styler.config import StylerConfig
from pbi_plot_styler.report import RestyleInvariantError, _assert_preserved, restyle_visual

COMBO = Path("definition/pages/overview/visuals/combo10/visual.json")


def _lit(v):
    return {"expr": {"Literal": {"Value": v}}}


def _solid(hex_):
    return {"solid": {"color": _lit(f"'{hex_}'")}}


ONLINE = [{"scopeId": {"Comparison": {
    "ComparisonKind": 0,
    "Left": {"Column": {"Expression": {"SourceRef": {"Entity": "Orders"}}, "Property": "Channel"}},
    "Right": _lit("'Online'"),
}}}]

# Ground truth: the entries brewbar's combo10 ships with.
DP_DEFAULT = {"properties": {"borderShow": _lit("false"), "fillTransparency": _lit("10L"), "fill": _solid("#333333")}}
DP_COLUMNS_REVENUE = {"properties": {"fill": _solid("#AA0000")}, "selector": {"metadata": "Sales Measures.Revenue"}}
DP_LEGEND = {"properties": {"fill": _solid("#00AA00")}, "selector": {"data": ONLINE}}
LB_LEGEND = {"properties": {"showSeries": _lit("false")}, "selector": {"data": ONLINE}}

LINE_KEYS = [  # y-Plot Specific, sorted; Legacy KPI sits in a block comment
    "Sales Measures.Avg Ticket",
    "Sales Measures.Margin %",
    "Sales Measures.Orders #",
    "Sales Measures.Revenue",
    "Sales Measures.Revenue v1.2 (Adj.)",
]


def _style(report: Path, *args: str):
    result = CliRunner().invoke(main, [str(report), *args])
    assert result.exit_code == 0, result.output
    return json.loads((report / COMBO).read_text(encoding="utf-8"))["visual"]["objects"]


def _meta(entries):
    return [e["selector"]["metadata"] for e in entries if "metadata" in (e.get("selector") or {})]


def test_fixture_ground_truth_is_what_the_tests_assume(brewbar_report):
    objects = json.loads((brewbar_report / COMBO).read_text(encoding="utf-8"))["visual"]["objects"]
    assert objects["dataPoint"][0] == DP_DEFAULT
    assert objects["dataPoint"][1] == DP_COLUMNS_REVENUE
    assert DP_LEGEND in objects["dataPoint"]
    assert LB_LEGEND in objects["labels"]


def test_layout_defaults_excluded_styled_then_data_scoped(brewbar_report):
    objects = _style(brewbar_report, "--exclude-role", "Y")
    dp = objects["dataPoint"]
    # [defaults] + [excluded metadata] + [styled metadata] + [data-scoped]
    assert dp[0] == DP_DEFAULT
    assert dp[1] == DP_COLUMNS_REVENUE
    assert _meta(dp[2:-1]) == [
        "Sales Measures.Avg Ticket",
        "Sales Measures.Margin %",
        "Sales Measures.Revenue v1.2 (Adj.)",
    ]
    assert dp[-1] == DP_LEGEND
    assert objects["labels"][-1] == LB_LEGEND


def test_columns_role_field_parameter_excludes_its_whole_catalog(brewbar_report):
    # Y is bound through the "Bar Metrics" field parameter (Revenue, Orders #),
    # so both stay out of the line styling, and Revenue's hand-picked column
    # fill survives verbatim.
    objects = _style(brewbar_report, "--exclude-role", "Y")
    styled = _meta(objects["dataPoint"])
    assert "Sales Measures.Orders #" not in styled
    assert styled.count("Sales Measures.Revenue") == 1
    assert DP_COLUMNS_REVENUE in objects["dataPoint"]
    assert "Sales Measures.Revenue" not in _meta(objects["labels"])


def test_without_exclusion_every_line_measure_is_styled(brewbar_report):
    objects = _style(brewbar_report)
    assert _meta(objects["dataPoint"]) == LINE_KEYS
    revenue = next(e for e in objects["dataPoint"] if (e.get("selector") or {}).get("metadata") == "Sales Measures.Revenue")
    assert revenue["properties"]["fill"] == _solid("#118DFF")


def test_hand_tuned_siblings_survive_and_owned_props_change(brewbar_report):
    objects = _style(brewbar_report, "--exclude-role", "Y")
    avg = next(e for e in objects["dataPoint"] if (e.get("selector") or {}).get("metadata") == "Sales Measures.Avg Ticket")
    assert avg["properties"] == {"fill": _solid("#118DFF"), "fillTransparency": _lit("15L")}

    margin = next(e for e in objects["labels"] if (e.get("selector") or {}).get("metadata") == "Sales Measures.Margin %")
    # backgroundColor is owned; the hand-set 30L transparency and the custom
    # label text color are not.
    assert margin["properties"] == {
        "backgroundColor": _solid("#118DFF"),
        "backgroundTransparency": _lit("30L"),
        "color": _solid("#FAFAFA"),
    }
    seeded = next(e for e in objects["labels"] if (e.get("selector") or {}).get("metadata") == "Sales Measures.Avg Ticket")
    assert seeded["properties"]["backgroundTransparency"] == _lit("20L")


def test_explicit_transparency_is_enforced_on_hand_tuned_entries(brewbar_report):
    objects = _style(brewbar_report, "--label-transparency", "0")
    margin = next(e for e in objects["labels"] if (e.get("selector") or {}).get("metadata") == "Sales Measures.Margin %")
    assert margin["properties"]["backgroundTransparency"] == _lit("0L")
    assert margin["properties"]["color"] == _solid("#FAFAFA")


def test_existing_labels_default_kept_and_only_enable_background_added(brewbar_report):
    objects = _style(brewbar_report)
    defaults = [e for e in objects["labels"] if not e.get("selector")]
    assert defaults == [{"properties": {
        "show": _lit("true"),
        "color": _solid("#111111"),
        "fontSize": _lit("9D"),
        "enableBackground": _lit("true"),
    }}]


def test_explicit_label_settings_update_the_existing_default(brewbar_report):
    objects = _style(brewbar_report, "--hide-labels", "--label-color", "#FFFFFF")
    default = objects["labels"][0]["properties"]
    assert default["show"] == _lit("false")
    assert default["color"] == _solid("#FFFFFF")
    assert default["fontSize"] == _lit("9D")


def test_stale_metadata_entry_is_dropped(brewbar_report):
    objects = _style(brewbar_report)
    assert "Sales Measures.Legacy KPI" not in _meta(objects["dataPoint"])


def test_no_datapoint_default_is_invented():
    visual = {"visual": {"visualType": "lineClusteredColumnComboChart", "objects": {}}}
    data = restyle_visual(visual, ["T.A"], StylerConfig())
    assert all(e.get("selector") for e in data["visual"]["objects"]["dataPoint"])


def test_rerun_is_byte_identical(brewbar_report):
    _style(brewbar_report, "--exclude-role", "Y")
    before = (brewbar_report / COMBO).read_bytes()
    result = CliRunner().invoke(main, [str(brewbar_report), "--exclude-role", "Y", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "already styled" in result.output
    assert (brewbar_report / COMBO).read_bytes() == before


def test_invariant_guard_rejects_a_dropped_data_scoped_entry():
    original = {"dataPoint": [DP_LEGEND], "labels": []}
    with pytest.raises(RestyleInvariantError):
        _assert_preserved(original, {"dataPoint": [], "labels": []}, set())
    with pytest.raises(RestyleInvariantError):
        _assert_preserved({"dataPoint": [DP_DEFAULT], "labels": []}, {"dataPoint": [], "labels": []}, set())
    with pytest.raises(RestyleInvariantError):
        _assert_preserved(
            {"dataPoint": [DP_COLUMNS_REVENUE], "labels": []},
            {"dataPoint": [], "labels": []},
            {"Sales Measures.Revenue"},
        )


def test_crlf_line_endings_are_preserved(brewbar_report):
    path = brewbar_report / COMBO
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    _style(brewbar_report)
    raw = path.read_bytes()
    assert b"\r\n" in raw
    assert b"\n" not in raw.replace(b"\r\n", b"")
    assert raw.endswith(b"\r\n")


def test_an_entry_with_an_unknown_selector_shape_is_kept():
    lit = {"expr": {"Literal": {"Value": "'#123456'"}}}
    odd = {"properties": {"fill": {"solid": {"color": lit}}}, "selector": {"id": "x", "metadata": "M.A"}}
    visual = {"visual": {"visualType": "lineClusteredColumnComboChart", "objects": {"dataPoint": [odd]}}}
    out = restyle_visual(visual, ["M.A"], StylerConfig())
    assert odd in out["visual"]["objects"]["dataPoint"]

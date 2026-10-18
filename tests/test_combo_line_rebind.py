"""F-combo-line-format: stale line rebind and the formatting rebuild.

New tests (the rebind rule is pinned by no original test; the original
``test_impose_combo_chart_format`` is ported in test_combo_line_format.py).
Model ``fixtures/shop-combo``: table ``Shop Measures`` with ``Revenue``,
``Basket Size``, ``Avg Basket Size``, ``Qualifier Margin``, ``Clicks``;
selector ``x-Plot Specific 2`` offers Revenue, Qualifier Margin and
Avg Basket Size (and one column, which falls away).

Parity configuration: ``--rebind-stale-line --theme-color-id 9
--theme-color-percent 0`` with ``[style] touch_existing_label_default = false``
and the seeded default labels properties of the spec.
"""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

from ported_helpers import copy_fixture, dump, load, run, write_toml

TABLE = "Shop Measures"
THEME9 = {"solid": {"color": {"expr": {"ThemeDataColor": {"ColorId": 9, "Percent": 0}}}}}
STYLED = ["Shop Measures.Avg Basket Size", "Shop Measures.Qualifier Margin", "Shop Measures.Revenue"]


def _measure(entity: str, prop: str, query_ref: str | None = None) -> dict:
    p = {"field": {"Measure": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}}
    p["queryRef"] = query_ref if query_ref is not None else f"{entity}.{prop}"
    p["nativeQueryRef"] = prop
    return p


def _combo(y2: dict, objects: dict | None = None, y: dict | None = None) -> dict:
    v = {
        "visualType": "lineStackedColumnComboChart",
        "query": {"queryState": {
            "Category": {"projections": [{"field": {"Column": {"Expression": {"SourceRef": {"Entity": "Calendar"}},
                                                               "Property": "Month"}}}]},
            "Y": {"projections": [y or _measure(TABLE, "Clicks")]},
            "Y2": {"projections": [y2]},
        }},
    }
    if objects is not None:
        v["objects"] = objects
    return {"name": "combo01", "position": {"x": 0, "y": 0, "z": 0, "width": 600, "height": 300}, "visual": v}


@pytest.fixture
def shop(tmp_path: Path) -> Path:
    return copy_fixture("shop-combo", tmp_path)


@pytest.fixture
def config(tmp_path: Path) -> Path:
    return write_toml(tmp_path / "plotstyler.toml", {"style": {
        "touch_existing_label_default": False,
        "label_default_properties": {
            "enableTitleDataLabel": "true", "titleContentType": "'Custom'", "enableBackground": "true"},
    }})


def _place(shop: Path, data: dict) -> Path:
    path = shop / "Shop.Report" / "definition" / "pages" / "combo" / "visuals" / "combo01" / "visual.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    dump(path, data)
    return path


def _style(shop: Path, config: Path, *extra):
    return run("style", shop / "Shop.Report", "--config", config, "--table", "x-Plot Specific 2",
               "--rebind-stale-line", "--theme-color-id", 9, "--theme-color-percent", 0, *extra)


def _y2(path: Path) -> dict:
    return load(path)["visual"]["query"]["queryState"]["Y2"]["projections"][0]


def _keys(entries: list) -> list:
    return [(e.get("selector") or {}).get("metadata") for e in entries]


# -- rebind cases 1-6 ------------------------------------------------------------
@pytest.mark.parametrize("old,expected,query_ref_after", [
    ("!Revenue", "Revenue", "Shop Measures.Revenue"),                         # 1 exact after strip
    ("- Margin", "Qualifier Margin", "Shop Measures.Qualifier Margin"),       # 2 single substring candidate
    ("!revenue", "Revenue", "Shop Measures.Revenue"),                         # 5 case-insensitive candidate
], ids=["case1-bang", "case2-substring", "case5-case-insensitive"])
def test_stale_line_rebinds(shop, config, old, expected, query_ref_after):
    path = _place(shop, _combo(_measure(TABLE, old)))
    result = _style(shop, config)
    assert result.exit_code == 0, result.output
    proj = _y2(path)
    assert proj["field"]["Measure"]["Property"] == expected
    assert proj["queryRef"] == query_ref_after
    assert proj["nativeQueryRef"] == old   # nothing else in the projection changes


@pytest.mark.parametrize("entity,old", [
    (TABLE, "!basket size"),    # 3 two candidates (Basket Size, Avg Basket Size)
    (TABLE, "!!!"),             # 4 empty after stripping
    ("Old Measures", "Revenue"),  # 6 entity is not a model table
], ids=["case3-ambiguous", "case4-empty", "case6-unknown-entity"])
def test_stale_line_left_alone(shop, config, entity, old):
    path = _place(shop, _combo(_measure(entity, old)))
    before = _y2(path)
    result = _style(shop, config)
    assert result.exit_code == 0, result.output
    assert _y2(path) == before
    # the visual is otherwise restyled
    assert _keys(load(path)["visual"]["objects"]["dataPoint"]) == STYLED


def test_case7_current_projection_untouched_and_check_clean(shop, config):
    path = _place(shop, _combo(_measure(TABLE, "Revenue")))
    before = _y2(path)
    assert _style(shop, config).exit_code == 0
    assert _y2(path) == before
    assert _style(shop, config, "--dry-run").exit_code == 0


def test_case8_check_reports_would_rebind(shop, config):
    path = _place(shop, _combo(_measure(TABLE, "!Revenue")))
    before = path.read_bytes()
    result = _style(shop, config, "--dry-run")
    assert result.exit_code == 1
    assert "would rebind" in result.output
    assert path.read_bytes() == before
    assert _style(shop, config).exit_code == 0
    assert _style(shop, config, "--dry-run").exit_code == 0


def test_rebind_is_off_by_default(shop, config):
    path = _place(shop, _combo(_measure(TABLE, "!Revenue")))
    result = run("style", shop / "Shop.Report", "--config", config, "--table", "x-Plot Specific 2",
                 "--theme-color-id", 9, "--theme-color-percent", 0)
    assert result.exit_code == 0, result.output
    assert _y2(path)["field"]["Measure"]["Property"] == "!Revenue"


# -- formatting rebuild ----------------------------------------------------------
def test_rebuild_order_colours_and_preserved_entries(shop, config):
    no_selector_dp = {"properties": {"fill": {"solid": {"color": {"expr": {"Literal": {"Value": "'#556677'"}}}}}}}
    data_scoped = {"properties": {"showSeries": {"expr": {"Literal": {"Value": "false"}}}},
                   "selector": {"data": [{"scopeId": {"Comparison": {"ComparisonKind": 0,
                                "Left": {"Column": {"Expression": {"SourceRef": {"Entity": "Calendar"}}, "Property": "Month"}},
                                "Right": {"Literal": {"Value": "'Jan'"}}}}}]}}
    column_side = {"properties": {"fill": {"solid": {"color": {"expr": {"Literal": {"Value": "'#010203'"}}}}}},
                   "selector": {"metadata": "Shop Measures.Clicks"}}
    retired = {"properties": {"fill": THEME9}, "selector": {"metadata": "Shop Measures.Retired Thing"}}
    kept_transparency = {"properties": {"backgroundTransparency": {"expr": {"Literal": {"Value": "30L"}}}},
                         "selector": {"metadata": "Shop Measures.Revenue"}}
    objects = {
        "dataPoint": [no_selector_dp, column_side, retired, data_scoped],
        "labels": [kept_transparency, copy.deepcopy(data_scoped)],
    }
    path = _place(shop, _combo(_measure(TABLE, "Revenue"), objects))
    assert _style(shop, config).exit_code == 0
    out = load(path)["visual"]["objects"]

    dp = out["dataPoint"]
    assert dp[0] == no_selector_dp
    assert dp[1] == column_side
    assert _keys(dp[2:5]) == STYLED
    assert all(e["properties"]["fill"] == THEME9 for e in dp[2:5])
    assert dp[5] == data_scoped
    assert "Shop Measures.Retired Thing" not in _keys(dp)       # retired key dropped
    assert "Shop Measures.Clicks" in _keys(dp) and _keys(dp).count("Shop Measures.Clicks") == 1

    labels = out["labels"]
    default = labels[0]
    assert "selector" not in default
    assert set(default["properties"]) == {"enableTitleDataLabel", "titleContentType", "enableBackground"}
    assert default["properties"]["titleContentType"] == {"expr": {"Literal": {"Value": "'Custom'"}}}
    by_key = {(e.get("selector") or {}).get("metadata"): e for e in labels[1:]}
    revenue = by_key["Shop Measures.Revenue"]["properties"]
    assert revenue["backgroundColor"] == THEME9
    assert revenue["backgroundTransparency"] == {"expr": {"Literal": {"Value": "30L"}}}   # kept
    margin = by_key["Shop Measures.Qualifier Margin"]["properties"]
    assert margin["backgroundTransparency"] == {"expr": {"Literal": {"Value": "20L"}}}   # seeded
    assert labels[-1] == data_scoped


def test_existing_label_default_stays_as_found(shop, config):
    existing_default = {"properties": {"show": {"expr": {"Literal": {"Value": "true"}}}}}
    path = _place(shop, _combo(_measure(TABLE, "Revenue"), {"labels": [existing_default]}))
    assert _style(shop, config).exit_code == 0
    labels = load(path)["visual"]["objects"]["labels"]
    assert labels[0] == existing_default    # no enableBackground added
    assert "dataPoint" not in load(path)["visual"]["objects"] or all(
        e.get("selector") for e in load(path)["visual"]["objects"]["dataPoint"])  # no made-up default


def test_second_run_writes_nothing(shop, config):
    path = _place(shop, _combo(_measure(TABLE, "!Revenue")))
    assert _style(shop, config).exit_code == 0
    first = path.read_bytes()
    assert _style(shop, config).exit_code == 0
    assert path.read_bytes() == first
    assert first.decode("utf-8").endswith("\n")

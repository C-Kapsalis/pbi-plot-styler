"""Formatting rebuild: entry shapes, palettes, determinism, idempotency."""
from __future__ import annotations

import json

from pbi_plot_styler.config import StylerConfig
from pbi_plot_styler.report import (
    dump_visual,
    plan_changes,
    restyle_visual,
    resolve_model_dir,
)
from pbi_plot_styler.tmdl import SemanticModel

from conftest import EXPECTED_KEYS


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _combo01(report_dir):
    return (
        report_dir
        / "definition"
        / "pages"
        / "monthlyperformance"
        / "visuals"
        / "combo01"
        / "visual.json"
    )


def test_datapoint_entries_rebuilt_per_measure(report_dir):
    config = StylerConfig()
    data = restyle_visual(_load(_combo01(report_dir)), EXPECTED_KEYS, config)
    datapoints = data["visual"]["objects"]["dataPoint"]

    assert [d["selector"]["metadata"] for d in datapoints] == EXPECTED_KEYS
    for entry in datapoints:
        color = entry["properties"]["fill"]["solid"]["color"]
        assert color == {"expr": {"Literal": {"Value": "'#118DFF'"}}}
    # The stale entry for the retired measure is gone.
    assert not any(
        "Retired Blend Sales" in d["selector"]["metadata"] for d in datapoints
    )


def test_labels_default_entry_then_one_per_measure(report_dir):
    config = StylerConfig(label_transparency=35, label_color="#FFFFFF")
    data = restyle_visual(_load(_combo01(report_dir)), EXPECTED_KEYS, config)
    labels = data["visual"]["objects"]["labels"]

    assert len(labels) == len(EXPECTED_KEYS) + 1

    default = labels[0]
    assert "selector" not in default
    assert default["properties"]["show"] == {"expr": {"Literal": {"Value": "true"}}}
    assert default["properties"]["enableBackground"] == {
        "expr": {"Literal": {"Value": "true"}}
    }
    assert default["properties"]["color"]["solid"]["color"] == {
        "expr": {"Literal": {"Value": "'#FFFFFF'"}}
    }

    for entry, key in zip(labels[1:], EXPECTED_KEYS):
        assert entry["selector"]["metadata"] == key
        assert entry["properties"]["backgroundTransparency"] == {
            "expr": {"Literal": {"Value": "35L"}}
        }
        # Default: background matches the line color.
        assert entry["properties"]["backgroundColor"]["solid"]["color"] == {
            "expr": {"Literal": {"Value": "'#118DFF'"}}
        }


def test_hide_labels(report_dir):
    config = StylerConfig(show_labels=False)
    data = restyle_visual(_load(_combo01(report_dir)), EXPECTED_KEYS, config)
    default = data["visual"]["objects"]["labels"][0]
    assert default["properties"]["show"] == {"expr": {"Literal": {"Value": "false"}}}


def test_palette_cycles_per_measure_and_backgrounds_follow(report_dir):
    config = StylerConfig(palette=("#111111", "#222222"))
    data = restyle_visual(_load(_combo01(report_dir)), EXPECTED_KEYS, config)

    fills = [
        d["properties"]["fill"]["solid"]["color"]["expr"]["Literal"]["Value"]
        for d in data["visual"]["objects"]["dataPoint"]
    ]
    assert fills == ["'#111111'", "'#222222'", "'#111111'", "'#222222'", "'#111111'"]

    backgrounds = [
        l["properties"]["backgroundColor"]["solid"]["color"]["expr"]["Literal"]["Value"]
        for l in data["visual"]["objects"]["labels"][1:]
    ]
    assert backgrounds == fills


def test_explicit_label_background_wins_over_palette(report_dir):
    config = StylerConfig(palette=("#111111", "#222222"), label_background="#333333")
    data = restyle_visual(_load(_combo01(report_dir)), EXPECTED_KEYS, config)
    backgrounds = {
        l["properties"]["backgroundColor"]["solid"]["color"]["expr"]["Literal"]["Value"]
        for l in data["visual"]["objects"]["labels"][1:]
    }
    assert backgrounds == {"'#333333'"}


def test_other_objects_and_query_are_untouched(report_dir):
    raw = _load(_combo01(report_dir))
    data = restyle_visual(raw, EXPECTED_KEYS, StylerConfig())
    assert data["visual"]["objects"]["seriesLabels"] == raw["visual"]["objects"]["seriesLabels"]
    assert data["visual"]["query"] == raw["visual"]["query"]
    assert data["position"] == raw["position"]


def test_restyle_is_deterministic_and_idempotent(report_dir):
    config = StylerConfig()
    once = restyle_visual(_load(_combo01(report_dir)), EXPECTED_KEYS, config)
    twice = restyle_visual(once, EXPECTED_KEYS, config)
    assert dump_visual(once) == dump_visual(twice)


def test_plan_targets_only_configured_visual_types(report_dir, model_dir):
    model = SemanticModel.load(model_dir)
    keys = model.field_parameter_measures(StylerConfig().field_parameter_tables)
    changes = plan_changes(report_dir, keys, StylerConfig())
    names = sorted(c.path.parent.name for c in changes)
    assert names == ["combo01", "combo02"]  # slicer01 is never touched


def test_resolve_model_dir_via_pbir(report_dir, model_dir):
    assert resolve_model_dir(report_dir) == model_dir.resolve()

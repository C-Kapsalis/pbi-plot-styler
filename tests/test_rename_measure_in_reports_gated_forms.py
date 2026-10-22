"""The four report-layer forms that fail SILENTLY when a rename misses them.

`Measure.Property` / `queryRef` / `metadata` / `nativeQueryRef` dangle loudly —
the visual breaks and someone reports it. These four do not: the bookmark simply
restores a selection that no longer exists, and the report renders its fallback.

They were unhandled until 2026-08-28 and were 390 of the 1024 live references for
a single measure (`CPA`, PBI#545). Each is GATED on a sibling that provably binds
the measure, and the label forms additionally require the label to still equal the
old name — a hand-customised label belongs to a human. These tests pin both
halves: that the forms are rewritten, and that the gates refuse everything else.
"""
from __future__ import annotations

import copy

import pytest

from pbi_plot_styler.rename import count_tree, rewrite_tree

pytestmark = [pytest.mark.p1, pytest.mark.layer3_5]

OLD, NEW = "CPA", "Cost/ Conversion"


def _selection(measure: str) -> dict:
    """The DAX literal a bookmark stores for an x-Selector field-parameter choice."""
    return {"scopeId": {"Comparison": {
        "ComparisonKind": 0,
        "Left": {"Column": {"Expression": {"SourceRef": {"Entity": "x-Selector 2"}},
                            "Property": "x-Selector 2 Fields"}},
        "Right": {"Literal": {"Value": f"'''#Report Measures''[{measure}]'"}}}}}


def test_dax_string_literal_selection_is_rewritten():
    node = {"Literal": {"Value": "'''#Report Measures''[CPA]'"}}
    assert rewrite_tree(node, OLD, NEW) == 1
    assert node["Literal"]["Value"] == "'''#Report Measures''[Cost/ Conversion]'"


def test_cached_filter_display_item_follows_its_own_id():
    node = {"cachedFilterDisplayItems": [
        {"id": _selection("CPA"), "displayName": "CPA"},
        {"id": _selection("!CPA"), "displayName": "CPA"},      # a DIFFERENT measure
        {"id": _selection("Cost"), "displayName": "Cost"},
    ]}
    rewrite_tree(node, OLD, NEW)
    got = [i["displayName"] for i in node["cachedFilterDisplayItems"]]
    assert got == ["Cost/ Conversion", "CPA", "Cost"], \
        "only the item whose id binds [CPA] may be relabelled"


def test_projection_display_name_follows_its_own_queryref():
    node = {"Values": {"projections": [
        {"displayName": "CPA", "queryRef": "#Report Measures.CPA",
         "nativeQueryRef": "CPA", "field": {}},
        {"displayName": "CPA", "queryRef": "#Report Measures.Clicks #",
         "nativeQueryRef": "Clicks #", "field": {}},          # unrelated field
    ]}}
    rewrite_tree(node, OLD, NEW)
    labels = [p["displayName"] for p in node["Values"]["projections"]]
    assert labels == ["Cost/ Conversion", "CPA"]


def test_value_map_pairs_positionally_with_decomposed_identities():
    node = {"filterExpressionMetadata": {
        "decomposedIdentities": {"values": [
            [{"0": [{"Literal": {"Value": "'''#Report Measures''[Cost]'"}}]}],
            [{"0": [{"Literal": {"Value": "'''#Report Measures''[CPA]'"}}]}],
            [{"0": [{"Literal": {"Value": "'''#Report Measures''[!CPA]'"}}]}],
        ]},
        "valueMap": [{"0": "Cost"}, {"0": "CPA"}, {"0": "CPA"}],
    }}
    rewrite_tree(node, OLD, NEW)
    assert [e["0"] for e in node["filterExpressionMetadata"]["valueMap"]] == \
        ["Cost", "Cost/ Conversion", "CPA"]


def test_a_customised_label_is_left_for_a_human():
    """The label gate is equality with the OLD NAME, not 'anything on this id'."""
    node = {"cachedFilterDisplayItems": [
        {"id": _selection("CPA"), "displayName": "Acquisition cost (legacy)"}]}
    rewrite_tree(node, OLD, NEW)
    assert node["cachedFilterDisplayItems"][0]["displayName"] == "Acquisition cost (legacy)"


def test_an_explicit_label_pair_is_honoured():
    node = {"Values": {"projections": [
        {"displayName": "CPA short", "queryRef": "#Report Measures.CPA",
         "nativeQueryRef": "CPA", "field": {}}]}}
    rewrite_tree(node, OLD, NEW, "CPA short", "C/Conv")
    assert node["Values"]["projections"][0]["displayName"] == "C/Conv"


def test_count_predicts_rewrite_exactly():
    """A dry run that cannot predict the apply is worse than no dry run."""
    doc = {
        "singleVisual": {"cachedFilterDisplayItems": [
            {"id": _selection("CPA"), "displayName": "CPA"},
            {"id": _selection("!CPA"), "displayName": "CPA"}]},
        "filterExpressionMetadata": {
            "decomposedIdentities": {"values": [
                [{"0": [{"Literal": {"Value": "'''#Report Measures''[CPA]'"}}]}]]},
            "valueMap": [{"0": "CPA"}]},
        "Values": [{"Measure": {"Expression": {"SourceRef": {"Entity": "#Report Measures"}},
                                "Property": "CPA"},
                    "queryRef": "#Report Measures.CPA",
                    "nativeQueryRef": "CPA"}],
        "metadata": "#Report Measures.CPA",
    }
    predicted = count_tree(copy.deepcopy(doc), OLD)
    applied = rewrite_tree(copy.deepcopy(doc), OLD, NEW)
    assert predicted == applied


def test_a_column_named_the_same_is_never_touched():
    node = {"Column": {"Expression": {"SourceRef": {"Entity": "t"}}, "Property": "CPA"}}
    assert rewrite_tree(node, OLD, NEW) == 0
    assert node["Column"]["Property"] == "CPA"

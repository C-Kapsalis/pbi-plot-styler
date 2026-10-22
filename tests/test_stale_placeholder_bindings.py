"""No saved report state may reference a blank-dimension placeholder its bound
y-axis field parameter does not offer (``--rule stale-placeholders``,
F-stale-placeholder-bindings).

A y- field parameter offers exactly one '#Report Measures' placeholder as its
"no dimension" row ([z] on the numbered axes, [z_space] on y-Plot Specific 1).
Reports cache the selected field, so retargeting an axis leaves stale
bindings. Judged per report against its own paired model. A role binding two
axes that offer different placeholders is reported as SKIPPED and never fails.

Each case runs on a tmp copy: check -> check --fix -> re-check.
"""
from __future__ import annotations

import json

import pytest

from canvas_variants import VARIANTS
from cli_helpers import (  # noqa: F401  (fixtures imported for registration)
    EXIT_FINDINGS, EXIT_OK, check_json, of, report_context, run, universal,
)

pytestmark = [pytest.mark.p0, pytest.mark.layer3_5, pytest.mark.visual_architecture]


def test_no_stale_placeholder_bindings(universal):
    client_dir = universal
    first = check_json(client_dir, "stale-placeholders")
    assert first["exit_code"] == EXIT_OK, first["findings"]


def test_stale_series_binding_is_fixed(universal):
    VARIANTS["stale-series"](universal)
    first = check_json(universal, "stale-placeholders")
    assert first["exit_code"] == EXIT_FINDINGS          # findings before the fix
    assert len(of(first, "STALE")) == 1
    fix = run("check", universal, "--rule", "stale-placeholders", "--fix")
    assert fix.exit_code == EXIT_OK, fix.output
    second = check_json(universal, "stale-placeholders")
    assert second["exit_code"] == EXIT_OK              # clean after the fix
    combo = universal / "-Report.Report/definition/pages/a0b1c2d3e4f5a6b7c8d9/visuals/combo_main/visual.json"
    p = json.loads(combo.read_text(encoding="utf-8"))["visual"]["query"]["queryState"]["Series"]["projections"][0]
    assert p["field"]["Column"]["Property"] == "z_space"
    assert p["queryRef"] == "#Report Measures.z_space"


def test_ambiguous_role_is_skipped_not_failed(universal):
    VARIANTS["stale-ambiguous"](universal)
    payload = check_json(universal, "stale-placeholders")
    assert payload["exit_code"] == EXIT_OK
    assert not of(payload, "STALE")
    assert any("ambiguous" in note.lower() for note in payload.get("skipped", []))
    before = (universal / "-Report.Report/definition/bookmarks/bA00000000000000000a.bookmark.json").read_bytes()
    assert run("check", universal, "--rule", "stale-placeholders", "--fix").exit_code == EXIT_OK
    after = (universal / "-Report.Report/definition/bookmarks/bA00000000000000000a.bookmark.json").read_bytes()
    assert after == before


def test_other_bookmark_json_files_with_exploration_state_are_read(universal):
    col = lambda e, p: {"Column": {"Expression": {"SourceRef": {"Entity": e}}, "Property": p}}  # noqa: E731
    state = {"explorationState": {"activeSection": "a0b1c2d3e4f5a6b7c8d9", "sections": {
        "a0b1c2d3e4f5a6b7c8d9": {"visualContainers": {"combo_main": {"singleVisual": {
            "parameters": {"Series": [{"expr": col("y-Plot Specific 1", "y-Plot Specific 1"),
                                       "index": 0, "length": 1}]},
            "projections": {"Series": [col("#Report Measures", "z")]}}}}}}}}
    path = universal / "-Report.Report/definition/bookmarks/exploration-state.json"
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    payload = check_json(universal, "stale-placeholders")
    hits = of(payload, "STALE")
    assert [h["file"].rsplit("/", 1)[-1] for h in hits] == ["exploration-state.json"]
    assert run("check", universal, "--rule", "stale-placeholders", "--fix").exit_code == EXIT_OK
    fixed = json.loads(path.read_text(encoding="utf-8"))
    assert fixed["explorationState"]["sections"]["a0b1c2d3e4f5a6b7c8d9"]["visualContainers"][
        "combo_main"]["singleVisual"]["projections"]["Series"][0]["Column"]["Property"] == "z_space"

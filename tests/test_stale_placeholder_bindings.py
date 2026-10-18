"""
No saved report state may reference a blank-dimension placeholder its bound
y-axis field parameter does not offer (ported from the author's layer-3.5
suite; ``--rule stale-placeholders``, F-stale-placeholder-bindings).

A y- field parameter offers exactly one '#Report Measures' placeholder as its
"no dimension" row ([z] on the numbered axes, [z_space] on y-Plot Specific 1).
Reports cache the selected field, so retargeting an axis leaves stale
bindings. Judged per report against its own paired model. A role binding two
axes that offer different placeholders is reported as SKIPPED and never fails.

The original ran once per client folder (guard dropped here: tmp copy) and,
with PBI_AUTOFIX=1, fixed and re-checked. The port always runs check ->
check --fix -> re-check.
"""
from __future__ import annotations

import json

import pytest

from canvas_variants import VARIANTS
from ported_helpers import (  # noqa: F401  (fixtures imported for registration)
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
    assert first["exit_code"] == EXIT_FINDINGS          # original verdict, PBI_AUTOFIX=0
    assert len(of(first, "STALE")) == 1
    fix = run("check", universal, "--rule", "stale-placeholders", "--fix")
    assert fix.exit_code == EXIT_OK, fix.output
    second = check_json(universal, "stale-placeholders")
    assert second["exit_code"] == EXIT_OK              # original verdict, PBI_AUTOFIX=1
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

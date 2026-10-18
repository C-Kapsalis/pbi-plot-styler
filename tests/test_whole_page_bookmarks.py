"""
Whole-page answer bookmarks: bookmark, visual-capture and page level.

Ported from the author's layer-3.5 suite. The levels say where the fix goes:

  bookmark level   (T1, T7, T8)            the bookmark's own options and registration
  capture level    (T3, T4, T5, T9, T10)   what the bookmark persists per visual
  page level       (P1, P2, P3)            the page definition; no bookmark overrides it

Scope: whole-page category bookmarks named '<Analysis Category> | <Aspect>' on
the stand-in report tests/fixtures/spinout_02_db/-Insights.Report. The
stand-in reuses the original page and visual ids, so the original suite and the
tool read the same objects (parity-expected.json records the original's
verdicts on the stand-in and on every defect variant).

A RATCHET, not a list of exceptions: accepted findings live in a generated
baseline (tests/baselines/whole_page_bookmark_floors.json, styler
``--update-baseline`` format) and each test fails only on findings NOT in it.
On the stand-in the baseline accepts one T1 finding ("CRM Deals | Owners", a
bookmark saved by the service with a visual selected).

Every test runs twice: once with the page / visual ids configured, once with
discovery only. Both must give the same findings.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from answer_bookmark_variants import (
    CATEGORY_PREFIXES, INHERITED, MAIN_PAGE, MATRIX, PARAM_SLICER, ROW_DROPDOWNS,
    VARIANTS, no_prefix_match,
)
from ported_helpers import (
    BASELINES, EXIT_FINDINGS, EXIT_OK, FIXTURES, IDS, check_json, of, run, write_toml,
)

STAND_IN = FIXTURES / "spinout_02_db" / "-Insights.Report"
BASELINE = BASELINES / "whole_page_bookmark_floors.json"
PAGE_KEYS = ("P1", "P2")
FPM_KEYS = ("P3-overlap", "P3-range")

pytestmark = [pytest.mark.layer3_5, pytest.mark.visual_architecture]


def _config(path: Path, mode: str, prefixes=CATEGORY_PREFIXES) -> Path:
    answer = {
        "prefixes": list(prefixes),
        "inherited_fingerprints": list(INHERITED),
    }
    if mode == "configured":
        answer.update(
            main_page=MAIN_PAGE,
            matrix=MATRIX,
            slicers={k: v for k, v in PARAM_SLICER.items()},
            row_dropdowns=ROW_DROPDOWNS,
        )
    return write_toml(path, {
        "answer_bookmarks": answer,
        "panel": {"filter_tables": ["y-Selector 3", "y-Selector 4", "y-Selector 5", "y-Selector 6"]},
        "category": {"table": "z-Map Dimension-Measure Groupings", "column": "Analysis Category"},
        "placeholders": {"template_slot_table": "Helper Measures"},
    })


@pytest.fixture(params=["configured", "discovery"])
def mode(request) -> str:
    return request.param


@pytest.fixture
def report(tmp_path: Path) -> Path:
    dest = tmp_path / "spinout_02_db" / "-Insights.Report"
    shutil.copytree(STAND_IN, dest)
    return dest


@pytest.fixture
def baseline(tmp_path: Path) -> Path:
    dest = tmp_path / "whole_page_bookmark_floors.json"
    shutil.copy(BASELINE, dest)
    return dest


@pytest.fixture
def suite(report: Path, baseline: Path, tmp_path: Path, mode: str):
    """Run the answer-bookmark rule (T*, P1, P2) and the slot checks (P3)."""
    config = _config(tmp_path / "plotstyler.toml", mode)

    def go(with_baseline: bool = True) -> tuple[dict, dict]:
        extra = ["--baseline", baseline] if with_baseline else []
        answer = check_json(report, "answer-bookmarks", *extra, config=config)
        slots = run("check", report, "--json")
        return answer, json.loads(slots.output)

    return go


def _fresh(payload: dict, key: str) -> list[dict]:
    """The _ratchet of the original: findings for one check not in the baseline."""
    return of(payload, key, new_only=True)


# -- bookmark level --------------------------------------------------------------
@pytest.mark.p1
class TestBookmarkLevel:
    """The bookmark's own options and its registration in the UI."""

    def test_t1_targets_all_visuals(self, suite):
        answer, _ = suite()
        assert not _fresh(answer, "T1"), (
            "options.targetVisualNames must be PRESENT and EMPTY ([]); a list of "
            "visual ids scopes the bookmark to those visuals only.\n"
            + "\n".join(f["message"] for f in _fresh(answer, "T1")))
        # the accepted finding is still there, flagged as baselined
        accepted = of(answer, "T1")
        assert [f["subject"] for f in accepted] == ["CRM Deals | Owners"]
        assert all(f["baselined"] for f in accepted)

    def test_t1_without_the_baseline_fails(self, suite):
        """Original verdict with an empty baseline: fail (one T1 finding)."""
        answer, _ = suite(with_baseline=False)
        assert answer["exit_code"] == EXIT_FINDINGS
        assert [f["subject"] for f in of(answer, "T1")] == ["CRM Deals | Owners"]

    def test_t7_analysis_category_pinned(self, suite):
        answer, _ = suite()
        assert not _fresh(answer, "T7")

    def test_t8_registered_under_a_submenu(self, suite):
        answer, _ = suite()
        assert not _fresh(answer, "T8")


# -- capture level ---------------------------------------------------------------
@pytest.mark.p1
class TestVisualCaptureLevel:
    """What each bookmark persists for the main matrix."""

    def test_t3_matrix_captured_and_visible(self, suite):
        answer, _ = suite()
        assert not _fresh(answer, "T3")

    def test_t4_rows_are_this_bookmarks_own(self, suite):
        answer, _ = suite()
        assert not _fresh(answer, "T4")

    def test_t5_matrix_capture_shape(self, suite):
        answer, _ = suite()
        assert not _fresh(answer, "T5")

    def test_t9_every_declared_values_parameter_is_resolved(self, suite):
        answer, _ = suite()
        assert not _fresh(answer, "T9")

    def test_t10_row_dimensions_have_dropdown_filters(self, suite):
        answer, _ = suite()
        assert not _fresh(answer, "T10")


# -- page level ------------------------------------------------------------------
@pytest.mark.p1
class TestPageLevel:
    """The page definition. NO bookmark can override any of this."""

    def test_p1_parameter_wells_carry_no_raw_measures(self, suite):
        answer, _ = suite()
        assert not _fresh(answer, "P1")

    def test_p2_navigator_references_resolve(self, suite):
        answer, _ = suite()
        assert not _fresh(answer, "P2")

    def test_p3_parameter_slot_ranges_do_not_overlap(self, suite):
        _, slots = suite()
        assert not of(slots, "P3-overlap") and not of(slots, "P3-range")


@pytest.mark.p1
def test_the_gates_own_something(suite):
    """Guard against the whole suite passing vacuously."""
    answer, _ = suite()
    assert not of(answer, "vacuity")
    assert answer["exit_code"] == EXIT_OK


@pytest.mark.p1
def test_vacuity_guard_fails_when_no_bookmark_matches(report, baseline, tmp_path, mode):
    """Original verdict when no bookmark matches the prefixes: fail."""
    no_prefix_match(report)
    config = _config(tmp_path / "plotstyler.toml", mode)
    answer = check_json(report, "answer-bookmarks", "--baseline", baseline, config=config)
    assert answer["exit_code"] == EXIT_FINDINGS
    guard = of(answer, "vacuity")
    assert len(guard) == 1
    assert "CRM Deals |" in guard[0]["message"]  # names the prefixes


@pytest.mark.p1
def test_vacuity_guard_fails_when_prefixes_change(report, baseline, tmp_path, mode):
    config = _config(tmp_path / "plotstyler.toml", mode, prefixes=("Nothing Here |",))
    answer = check_json(report, "answer-bookmarks", "--baseline", baseline, config=config)
    assert answer["exit_code"] == EXIT_FINDINGS
    assert len(of(answer, "vacuity")) == 1


# -- defect variants (one defect each; original verdict recorded per variant) ----
@pytest.mark.parametrize("variant", sorted(VARIANTS))
def test_defect_variant_is_reported(variant, report, suite):
    mutate, _original, expected = VARIANTS[variant]
    mutate(report)
    answer, slots = suite()
    got = {}
    for key in IDS:
        payload = slots if key in FPM_KEYS else answer
        n = len(of(payload, key, new_only=True))
        if n:
            got[key] = n
    assert got == expected, (variant, got)
    assert answer["exit_code"] == EXIT_FINDINGS or set(expected) <= set(FPM_KEYS)


# -- the ratchet maps to --baseline / --update-baseline --------------------------
def test_update_baseline_captures_and_reports_healed(report, tmp_path, mode):
    config = _config(tmp_path / "plotstyler.toml", mode)
    fresh = tmp_path / "captured.json"
    capture = run("check", report, "--rule", "answer-bookmarks", "--config", config,
                  "--baseline", fresh, "--update-baseline")
    assert capture.exit_code == EXIT_OK, capture.output
    entries = json.loads(fresh.read_text(encoding="utf-8"))["findings"]
    assert [e["id"] for e in entries] == [IDS["T1"]]
    assert entries[0]["location"].endswith("::CRM Deals | Owners")
    # heal the accepted finding: the run passes and lists it as healed
    from answer_bookmark_variants import OWNERS, _bm, _edit
    _edit(_bm(report, OWNERS), lambda d: d["options"].update(targetVisualNames=[]))
    answer = check_json(report, "answer-bookmarks", "--baseline", fresh, config=config)
    assert answer["exit_code"] == EXIT_OK
    assert [h["id"] for h in answer["healed"]] == [IDS["T1"]]


def test_missing_baseline_file_is_a_usage_error(report, tmp_path, mode):
    """Kept stricter than the original (which treated it as empty)."""
    config = _config(tmp_path / "plotstyler.toml", mode)
    result = run("check", report, "--rule", "answer-bookmarks", "--config", config,
                 "--baseline", tmp_path / "absent.json")
    assert result.exit_code == 2

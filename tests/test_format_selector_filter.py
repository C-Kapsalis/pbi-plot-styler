"""
z-Selector Format report-level filter (ported from the author's layer-3.5 suite).

Every report must carry a hidden + locked report-level filter selecting the
'z-Selector Format'[Selector Format] = "Format" calculation item; without it
measures fall back to their raw format strings (``--rule format-selector``,
F-format-selector-filter).

Original outcomes: clean -> pass; incomplete -> patched (autofix) -> pass;
patch did not help -> fail. The port always runs the autofix path on a tmp
copy: check -> check --fix -> re-check clean.
"""
from __future__ import annotations

import json

import pytest

from canvas_variants import VARIANTS
from ported_helpers import (  # noqa: F401  (fixtures imported for registration)
    EXIT_FINDINGS, EXIT_OK, check_json, of, report_context, run, universal,
)


def _filters(report):
    data = json.loads((report / "definition" / "report.json").read_text(encoding="utf-8"))
    return [f for f in (data.get("filterConfig") or {}).get("filters", [])
            if (f.get("field") or {}).get("Column", {}).get("Property") == "Selector Format"]


@pytest.mark.layer3_5
@pytest.mark.visual_architecture
class TestFormatSelectorFilter:

    @pytest.mark.p0
    def test_format_selector_filter_present(self, report_context):
        first = check_json(report_context, "format-selector")
        assert first["exit_code"] == EXIT_OK, first["findings"]


@pytest.mark.parametrize("variant, reason", [
    ("format-no-filter-config", "no filter"),
    ("format-raw", "Format"),
    ("format-unlocked", "lock"),
    ("format-duplicates", "duplicate"),
], ids=["format-no-filter-config", "format-raw", "format-unlocked", "format-duplicates"])
def test_incomplete_filter_is_patched(universal, report_context, variant, reason):
    VARIANTS[variant](universal)
    first = check_json(report_context, "format-selector")
    assert first["exit_code"] == EXIT_FINDINGS        # original verdict, PBI_AUTOFIX=0
    hits = of(first, "FORMAT")
    assert len(hits) == 1 and reason.lower() in hits[0]["message"].lower()
    fix = run("check", report_context, "--rule", "format-selector", "--fix")
    assert fix.exit_code == EXIT_OK, fix.output       # original verdict, PBI_AUTOFIX=1
    second = check_json(report_context, "format-selector")
    assert second["exit_code"] == EXIT_OK
    kept = _filters(report_context)
    assert len(kept) == 1
    assert kept[0]["name"] == "format_selector_filter"  # existing name kept
    assert kept[0]["isHiddenInViewMode"] and kept[0]["isLockedInViewMode"]

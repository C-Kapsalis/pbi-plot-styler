"""Theme integration and visual placement.

THEME-ANY / THEME-BOTH / THEME-CUSTOM-MISSING are findings of ``--rule theme``
(F-theme-integration); visual x/y presence is ``--rule visual-position``
(F-visual-position-present). Sample client: tests/fixtures/universal.
"""
from __future__ import annotations

import pytest

from canvas_variants import VARIANTS
from cli_helpers import (  # noqa: F401  (fixtures imported for registration)
    EXIT_FINDINGS, EXIT_OK, check_json, of, report_context, universal,
)


@pytest.mark.layer3_5
@pytest.mark.visual_architecture
class TestThemeIntegration:

    @pytest.mark.p1
    def test_theme_data_color_usage(self, report_context):
        """At least a base or a custom theme is declared."""
        assert not of(check_json(report_context, "theme"), "THEME-ANY")

    @pytest.mark.p2
    def test_visual_container_objects_placement(self, report_context):
        """Every visual container has both x and y positions set."""
        payload = check_json(report_context, "visual-position")
        assert not of(payload, "POSITION"), payload["findings"]

    @pytest.mark.p1
    def test_theme_consistency(self, report_context):
        """Both baseTheme and customTheme are declared."""
        assert not of(check_json(report_context, "theme"), "THEME-BOTH")


# -- variants (one defect each) ---------------------------------------------------
def test_base_theme_only(universal, report_context):
    VARIANTS["theme-base-only"](universal)
    payload = check_json(report_context, "theme")
    both = of(payload, "THEME-BOTH")
    assert len(both) == 1 and "customTheme" in both[0]["message"]
    assert not of(payload, "THEME-ANY")
    warn = of(payload, "THEME-CUSTOM-MISSING")
    assert len(warn) == 1 and warn[0]["severity"] == "warning"


def test_empty_theme_collection(universal, report_context):
    VARIANTS["theme-empty"](universal)
    payload = check_json(report_context, "theme")
    assert payload["exit_code"] == EXIT_FINDINGS
    assert len(of(payload, "THEME-NONE")) == 1
    assert len(of(payload, "THEME-ANY")) == 1
    both = of(payload, "THEME-BOTH")
    assert len(both) == 1
    assert "baseTheme" in both[0]["message"] and "customTheme" in both[0]["message"]


def test_visual_missing_y_position(universal, report_context):
    VARIANTS["position-missing-y"](universal)
    payload = check_json(report_context, "visual-position")
    hits = of(payload, "POSITION")
    assert [h["subject"] for h in hits] == ["card_total"]
    assert hits[0]["severity"] == "error"
    assert payload["exit_code"] == 1

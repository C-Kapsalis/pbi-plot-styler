"""Report discovery shared by the canvas rules (F-canvas-config).

The original conftest parametrized one test per *.Report of the registry
client, excluded the API-only report family (M.Report, -M.Report) from
default and model-filtered sweeps, and included it only when targeted
explicitly; nothing matching was a skip, never a pass.
"""
from __future__ import annotations

from ported_helpers import EXIT_USAGE, check_json, run, universal  # noqa: F401


def test_default_sweep_excludes_the_api_only_report(universal):
    payload = check_json(universal, "theme")
    assert payload["reports"] == ["-Report.Report"]


def test_model_filter_keeps_the_exclusion(universal):
    payload = check_json(universal, "theme", "--model-name", "Performance")
    assert payload["reports"] == ["-Report.Report"]


def test_explicit_target_includes_the_api_only_report(universal):
    payload = check_json(universal, "theme", "--report", "M")
    assert payload["reports"] == ["M.Report"]
    assert payload["findings"]  # M.Report has no theme: it is checked, and fails


def test_nested_reports_are_discovered(tmp_path):
    from ported_helpers import copy_fixture
    client = copy_fixture("spinout_10_db", tmp_path)
    payload = check_json(client, "theme")
    assert sorted(payload["reports"]) == ["-Report.Report", "Finalized/Weekly.Report"]


def test_nothing_matched_is_not_a_pass(universal):
    result = run("check", universal, "--rule", "theme", "--report", "Absent")
    assert result.exit_code == EXIT_USAGE
    assert "Absent" in result.output

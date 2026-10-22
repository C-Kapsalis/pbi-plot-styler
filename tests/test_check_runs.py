"""``check`` runs as a whole: model loading, several reports under --fix,
scoped baselines, fixer dry runs, finding subjects and --summary."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from cli_helpers import check_json, copy_fixture, edit_json, load, run

from pbi_plot_styler.check import ReportContext, _check_field_parameter_slots


def _snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def _changed(before: dict[str, bytes], after: dict[str, bytes]) -> list[str]:
    return sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))


# -- a model that fails to load ----------------------------------------------------
def test_a_model_that_fails_to_load_is_an_error_not_a_silent_skip(tmp_path):
    client = copy_fixture("spinout_10_db", tmp_path)
    tables = client / "Growth.SemanticModel" / "definition" / "tables"
    shutil.rmtree(tables)
    payload = check_json(client, "format-selector")
    assert payload["exit_code"] == 1
    mdl = [f for f in payload["findings"] if f["id"] == "MDL001"]
    assert len(mdl) == 2 and all(f["file"].endswith("definition.pbir") for f in mdl)
    assert "TMDL tables directory" in mdl[0]["message"]
    # the skip note names the real cause, not a missing table
    assert all("could not be loaded" in n for n in payload["skipped"]), payload["skipped"]


def test_a_report_without_a_local_model_reference_is_only_a_note(tmp_path):
    client = copy_fixture("spinout_10_db", tmp_path)
    for pbir in client.rglob("definition.pbir"):
        edit_json(pbir, lambda d: d.update(datasetReference={"byConnection": {}}))
    payload = check_json(client, "format-selector")
    assert payload["exit_code"] == 0
    assert not [f for f in payload["findings"] if f["id"] == "MDL001"]
    assert payload["notes"] and all("no local semantic model" in n for n in payload["notes"])


# -- several reports under --fix ---------------------------------------------------
def _nested_universal(tmp_path: Path) -> Path:
    client = copy_fixture("universal", tmp_path)
    nested = client / "Finalized" / "Weekly.Report"
    shutil.copytree(client / "-Report.Report", nested)
    pbir = nested / "definition.pbir"
    pbir.write_text(pbir.read_text(encoding="utf-8").replace('"../', '"../../'), encoding="utf-8")
    return client


def test_slicer_mode_gates_resolve_the_model_of_a_nested_report(tmp_path):
    client = _nested_universal(tmp_path)
    payload = check_json(client, "slicer-mode-gates", "--fix")
    assert payload["exit_code"] == 0, payload
    files = sorted({f["file"] for f in payload["fixed"]})
    assert any(f.startswith("Finalized/Weekly.Report/") for f in files)
    assert any(f.startswith("-Report.Report/") for f in files)


def test_fix_validates_every_report_before_writing_any(tmp_path):
    client = _nested_universal(tmp_path)
    # the nested report now points at a model without the gate measures
    other = client / "Finalized" / "Other.SemanticModel"
    shutil.copytree(client / "Performance.SemanticModel", other)
    filters = other / "definition" / "tables" / "f-Filters.tmdl"
    filters.unlink()
    pbir = client / "Finalized" / "Weekly.Report" / "definition.pbir"
    pbir.write_text(pbir.read_text(encoding="utf-8").replace(
        "../../Performance.SemanticModel", "../Other.SemanticModel"), encoding="utf-8")
    before = _snapshot(client)
    result = run("check", client, "--rule", "slicer-mode-gates", "--fix")
    assert result.exit_code == 2, result.output
    assert "Finalized/Weekly.Report" in result.output
    assert result.output.startswith("!! could not find a table declaring both "
                                   "[f-Slicer] and [f-All] for ")
    assert _snapshot(client) == before


def test_a_fixer_failing_midway_names_the_files_it_already_wrote(tmp_path, monkeypatch):
    from pbi_plot_styler import rules as rules_mod
    from pbi_plot_styler.rules import gates

    client = _nested_universal(tmp_path)
    real = gates.fix_mode_gates
    calls = []

    def flaky(ctx):
        calls.append(ctx.label)
        if len(calls) == 2:
            raise rules_mod.RuleError(f"{ctx.label}: simulated failure")
        return real(ctx)

    registry = rules_mod.rules()
    monkeypatch.setitem(registry, "slicer-mode-gates",
                        registry["slicer-mode-gates"].__class__(
                            **{**registry["slicer-mode-gates"].__dict__, "fix": flaky}))
    result = run("check", client, "--rule", "slicer-mode-gates", "--fix")
    assert result.exit_code == 2
    assert "already written" in result.output
    assert "nothing was" not in result.output
    assert "bookmark.json" in result.output or "visual.json" in result.output


# -- scoped baselines --------------------------------------------------------------
def test_update_baseline_for_one_rule_keeps_the_other_entries(tmp_path):
    client = copy_fixture("universal", tmp_path)
    baseline = tmp_path / "b.json"
    assert run("check", client, "--baseline", baseline, "--update-baseline").exit_code == 0
    first = load(baseline)["findings"]
    assert len(first) == 4
    result = run("check", client, "--rule", "visual-position", "--baseline", baseline,
                 "--update-baseline")
    assert result.exit_code == 0, result.output
    assert load(baseline)["findings"] == first
    assert run("check", client, "--baseline", baseline).exit_code == 0


def test_update_baseline_for_one_report_keeps_the_other_reports(tmp_path):
    client = copy_fixture("spinout_10_db", tmp_path)
    baseline = tmp_path / "b.json"
    assert run("check", client, "--rule", "format-selector", "--baseline", baseline,
               "--update-baseline").exit_code == 0
    both = load(baseline)["findings"]
    assert len(both) == 2
    weekly = client / "Finalized" / "Weekly.Report"
    edit_json(weekly / "definition" / "report.json", lambda d: d.pop("filterConfig", None))
    result = run("check", client, "--rule", "format-selector", "--report", "-Report",
                 "--baseline", baseline, "--update-baseline")
    assert result.exit_code == 0, result.output
    assert load(baseline)["findings"] == both


def test_update_baseline_scoped_by_model_name(tmp_path):
    client = copy_fixture("universal", tmp_path)
    baseline = tmp_path / "b.json"
    baseline.write_text(json.dumps({"version": 1, "findings": [
        {"id": "BND001", "location": "Elsewhere.Report/definition/report.json::x"}]}),
        encoding="utf-8")
    assert run("check", client, "--model-name", "Performance", "--baseline", baseline,
               "--update-baseline").exit_code == 0
    locations = [f["location"] for f in load(baseline)["findings"]]
    assert "Elsewhere.Report/definition/report.json::x" in locations
    assert len(locations) == 5


# -- fixer dry runs ----------------------------------------------------------------
def test_fix_dry_run_prints_a_diff_and_writes_nothing(tmp_path):
    canvas = copy_fixture("gate-order", tmp_path)
    before = _snapshot(canvas)
    result = run("check", canvas, "--rule", "slicer-gates", "--fix", "--dry-run")
    assert result.exit_code == 1, result.output
    assert "would fix" in result.output
    assert "--- a/" in result.output and "+++ b/" in result.output
    assert _snapshot(canvas) == before


def test_fix_dry_run_json_lists_planned_changes(tmp_path):
    canvas = copy_fixture("mode-gates", tmp_path)
    before = _snapshot(canvas)
    payload = check_json(canvas, "slicer-mode-gates", "--fix", "--dry-run")
    assert payload["exit_code"] == 1
    assert payload["fixed"] == [] and payload["planned"]
    assert _snapshot(canvas) == before


def test_dry_run_without_fix_is_a_usage_error(tmp_path):
    canvas = copy_fixture("gate-order", tmp_path)
    assert run("check", canvas, "--dry-run").exit_code == 2


def test_filter_panel_refusal_exits_2_and_writes_nothing(tmp_path):
    from canvas_variants import VARIANTS

    client = copy_fixture("universal", tmp_path)
    VARIANTS["rule8-renamed"](client)
    page = next((client / "-Report.Report" / "definition" / "pages").glob("*/visuals/g1")).parent
    (page / "y_filters_group").mkdir()  # the target name is taken: the rename must refuse
    before = _snapshot(client)
    result = run("check", client / "-Report.Report", "--rule", "filter-panel", "--fix")
    assert result.exit_code == 2, result.output
    assert "REFUSING TO RENAME" in result.output
    assert _snapshot(client) == before
    dry = run("check", client / "-Report.Report", "--rule", "filter-panel", "--fix", "--dry-run")
    assert dry.exit_code == 2, dry.output
    assert _snapshot(client) == before


# -- FPM001 subjects ---------------------------------------------------------------
def test_fpm001_subject_drops_the_slot_but_keeps_one_finding_per_slot(tmp_path):
    def param(entity: str, index: int, length: int) -> dict:
        return {"parameterExpr": {"Column": {"Expression": {"SourceRef": {"Entity": entity}},
                                             "Property": entity}},
                "index": index, "length": length}

    data = {"visual": {"query": {"queryState": {"Y": {
        "projections": [{}, {}, {}],
        "fieldParameters": [param("x-A", 0, 2), param("x-B", 0, 2)]}}}}}
    ctx = ReportContext(tmp_path, tmp_path, None)
    _check_field_parameter_slots(ctx, tmp_path / "visual.json", data)
    overlaps = [f for f in ctx.findings if f.check_id == "FPM001"]
    assert len(overlaps) == 2
    assert {f.subject for f in overlaps} == {"Y:x-A|x-B"}
    assert len({f.key for f in overlaps}) == 2
    assert "slot 0" in overlaps[0].message and "slot 1" in overlaps[1].message


# -- --summary with errors ---------------------------------------------------------
def test_summary_is_not_compliant_while_errors_exist(tmp_path):
    client = copy_fixture("universal", tmp_path)
    report_json = client / "-Report.Report" / "definition" / "report.json"
    edit_json(report_json, lambda d: d.update(objects={"outspace": [{"properties": {"hexColor": "#1A2B3C"}}]}))
    result = run("check", client, "--summary", "--json")
    payload = json.loads(result.output)
    compliance = payload["compliance"]
    assert compliance["critical_violations"] >= 1
    assert compliance["overall_compliance"] is False
    theme = next(r for r in compliance["rules"] if r["rule"] == "theme")
    assert theme["compliant"] is False
    text = run("check", client, "--summary").output
    assert "## Rule #6: ThemeDataColor Integration ❌ FAIL" in text
    assert "**🔴 hardcoded_hex_colors** (report.json)" in text


def test_summary_theme_row_counts_only_the_rule_6_checks(tmp_path):
    client = copy_fixture("universal", tmp_path)
    report_json = client / "-Report.Report" / "definition" / "report.json"
    edit_json(report_json, lambda d: d["themeCollection"].pop("customTheme"))
    compliance = json.loads(run("check", client, "--summary", "--json").output)["compliance"]
    theme = next(r for r in compliance["rules"] if r["rule"] == "theme")
    assert theme["compliant"] is True
    assert (theme["errors"], theme["warnings"]) == (0, 1)
    assert compliance["overall_compliance"] is True
    assert (compliance["critical_violations"],
            compliance["warning_violations"]) == (0, 1)
    # the both-themes check still runs under --rule theme
    payload = json.loads(run("check", client, "--rule", "theme", "--json").output)
    assert "THM006" in {f["id"] for f in payload["findings"]}


def test_summary_findings_and_totals_agree_with_the_compliance(tmp_path):
    # BUGFIX: --summary printed `ERROR THM006` and closed with "1 error(s)"
    # under a 100.0% score; the summary counts only the rule-6 theme ids
    client = copy_fixture("universal", tmp_path)
    report_json = client / "-Report.Report" / "definition" / "report.json"
    edit_json(report_json, lambda d: d["themeCollection"].pop("customTheme"))
    result = run("check", client, "--summary")
    assert result.exit_code == 0, result.output
    assert "THM006" not in result.output
    assert "WARNING  THM003" in result.output
    assert "   Compliance Score: 100.0%" in result.output
    assert "Checked 1 report(s): 0 error(s), 1 warning(s)." in result.output
    payload = json.loads(run("check", client, "--summary", "--json").output)
    assert [f["id"] for f in payload["findings"]] == ["THM003"]
    assert (payload["summary"]["errors"], payload["summary"]["warnings"]) == (0, 1)
    assert payload["exit_code"] == 0


def test_summary_leaves_baseline_entries_of_the_unsummarised_ids_alone(tmp_path):
    client = copy_fixture("universal", tmp_path)
    report_json = client / "-Report.Report" / "definition" / "report.json"
    edit_json(report_json, lambda d: d["themeCollection"].pop("customTheme"))
    baseline = tmp_path / "b.json"
    assert run("check", client, "--rule", "theme", "--baseline", baseline,
               "--update-baseline").exit_code == 0
    assert "THM006" in {e["id"] for e in load(baseline)["findings"]}
    # a summary run neither calls the THM006 entry healed nor drops it
    result = run("check", client, "--summary", "--baseline", baseline)
    assert "THM006: 1 accepted finding(s) no longer occur" not in result.output
    assert run("check", client, "--summary", "--baseline", baseline,
               "--update-baseline").exit_code == 0
    assert "THM006" in {e["id"] for e in load(baseline)["findings"]}


# -- discovery ---------------------------------------------------------------------
def test_a_bare_sweep_over_a_folder_without_reports_exits_0(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    result = run("check", empty)
    assert result.exit_code == 0, result.output
    assert "nothing to check" in result.output
    payload = json.loads(run("check", empty, "--json").output)
    assert payload["exit_code"] == 0 and payload["reports"] == []


def test_a_filter_that_matches_nothing_still_exits_2(tmp_path):
    client = copy_fixture("universal", tmp_path)
    assert run("check", client, "--report", "No Such").exit_code == 2


def test_reports_in_nested_trees_are_found(tmp_path):
    root = tmp_path / "a" / "b"
    copy_fixture("universal", root)
    payload = json.loads(run("check", tmp_path, "--json").output)
    assert payload["reports"] == ["a/b/universal/-Report.Report"]


def test_fix_exits_from_the_recheck(tmp_path):
    canvas = copy_fixture("gate-order", tmp_path)
    gates = canvas / "Growth.SemanticModel" / "definition" / "tables" / "f-Filters.tmdl"
    gates.write_text("table 'f-Filters'\n\n\tmeasure 'f-All' = 1\n", encoding="utf-8")
    result = run("check", canvas, "--rule", "slicer-gates", "--fix")
    assert result.exit_code == 1, result.output   # the fix could not run; the re-check fails

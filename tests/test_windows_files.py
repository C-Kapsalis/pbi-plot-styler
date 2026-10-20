"""Files saved on Windows: a UTF-8 BOM and CRLF line endings.

Every reader accepts UTF-8 with or without a BOM and CRLF or LF; every
writer keeps the file's BOM and newline style. Each case runs a fixture as
committed (LF, no BOM) and as a Windows copy, and expects the same result.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from cli_helpers import FIXTURES, check_json, copy_fixture, run

BOM = b"\xef\xbb\xbf"
TEXT_SUFFIXES = {".json", ".tmdl", ".pbir", ".pbism", ".platform", ".toml"}


def to_windows(root: Path, *, bom: bool = True, crlf: bool = True,
               suffixes: set[str] = TEXT_SUFFIXES) -> None:
    for path in root.rglob("*"):
        if path.is_file() and (path.suffix in suffixes or path.name in suffixes):
            text = path.read_bytes().decode("utf-8-sig").replace("\r\n", "\n")
            if crlf:
                text = text.replace("\n", "\r\n")
            path.write_bytes((BOM if bom else b"") + text.encode("utf-8"))


def _findings(payload: dict) -> list[tuple]:
    return sorted((f["id"], f["file"], f["subject"]) for f in payload["findings"])


def _snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


CASES = [
    ("gate-order", "slicer-gates"),
    ("mode-gates", "slicer-mode-gates"),
    ("spinout_10_db", "format-selector"),
    ("universal", "slicer-mode-gates"),
]


@pytest.mark.parametrize("fixture,rule", CASES)
@pytest.mark.parametrize("suffix", sorted(TEXT_SUFFIXES - {".toml"}))
def test_a_bom_in_any_file_kind_changes_nothing(tmp_path, fixture, rule, suffix):
    lf = copy_fixture(fixture, tmp_path / "lf")
    win = copy_fixture(fixture, tmp_path / "win")
    to_windows(win, crlf=False, suffixes={suffix})
    a, b = check_json(lf, rule), check_json(win, rule)
    assert a["findings"], "the case must have something to find"
    assert _findings(b) == _findings(a)
    assert b["exit_code"] == a["exit_code"]
    assert b["notes"] == a["notes"]


@pytest.mark.parametrize("fixture,rule", CASES)
def test_fix_on_a_windows_copy_keeps_bom_and_crlf(tmp_path, fixture, rule):
    lf = copy_fixture(fixture, tmp_path / "lf")
    win = copy_fixture(fixture, tmp_path / "win")
    to_windows(win)
    before = _snapshot(win)
    lf_before = _snapshot(lf)
    assert check_json(lf, rule, "--fix")["exit_code"] == 0
    assert check_json(win, rule, "--fix")["exit_code"] == 0
    after, lf_after = _snapshot(win), _snapshot(lf)
    changed = sorted(k for k in after if before.get(k) != after[k])
    lf_changed = sorted(k for k in lf_after if lf_before.get(k) != lf_after[k])
    assert changed and changed == lf_changed
    for key in changed:
        raw = after[key]
        assert raw.startswith(BOM), key
        assert b"\n" not in raw.replace(b"\r\n", b""), key
        assert raw[3:].decode("utf-8").replace("\r\n", "\n") == lf_after[key].decode("utf-8"), key


def test_bom_in_definition_pbir_still_resolves_the_model(tmp_path):
    client = copy_fixture("spinout_10_db", tmp_path)
    to_windows(client, crlf=False, suffixes={".pbir"})
    payload = check_json(client, "format-selector")
    assert payload["exit_code"] == 1
    assert [f["id"] for f in payload["findings"]] == ["FMT001", "FMT001"]
    assert payload["notes"] == []


def test_bom_and_crlf_tmdl_tables_load(tmp_path):
    from pbi_plot_styler.tmdl import SemanticModel

    model = copy_fixture("color-sync", tmp_path) / "Shop.SemanticModel"
    plain = SemanticModel.load(model)
    to_windows(model, suffixes={".tmdl"})
    windows = SemanticModel.load(model)
    assert sorted(windows.raw_by_table) == sorted(plain.raw_by_table)
    assert windows.measures_by_table == plain.measures_by_table


def test_bom_toml_config_is_accepted_by_check(tmp_path):
    client = copy_fixture("universal", tmp_path)
    config = tmp_path / "plotstyler.toml"
    config.write_bytes(BOM + b'[canvas]\r\nexclude_reports = ["M.Report"]\r\n')
    payload = check_json(client, "visual-position", config=config)
    assert payload["reports"] == ["-Report.Report"]


def test_bom_display_name_filter_is_accepted(tmp_path):
    shop = copy_fixture("picker-literals", tmp_path)
    names = tmp_path / "names.json"
    names.write_bytes(BOM + json.dumps(["Nothing matches"]).encode("utf-8"))
    payload = check_json(shop, "bookmark-literals", "--only-display-names", names)
    assert payload["findings"] == []


def test_bom_entries_and_bom_builder_config_are_accepted(tmp_path):
    builder = copy_fixture("bookmark-builder", tmp_path)
    entries = tmp_path / "entries.json"
    entries.write_bytes(BOM + b'[{"displayName": "Letters | BOM"}]\r\n')
    config = tmp_path / "builder.toml"
    config.write_bytes(BOM + (builder / "builder.toml").read_bytes().replace(b"\n", b"\r\n"))
    result = run("bookmarks", "build", entries, "--report", builder / "Newsletter.Report",
                 "--config", config, "--dry-run")
    assert result.exit_code == 0, result.output
    assert result.output.startswith("would write ") and result.output.count("\n") == 1


def test_bom_visual_is_styled_and_keeps_its_bom(tmp_path):
    from shutil import copytree

    project = tmp_path / "roastery"
    copytree(FIXTURES / "roastery", project)
    report = project / "Roastery.Report"
    to_windows(report, suffixes={".json"})
    result = run("style", report)
    assert result.exit_code == 0, result.output
    styled = [p for p in report.rglob("visual.json")]
    assert styled and all(p.read_bytes().startswith(BOM) for p in styled)
    assert "Restyled 0/" not in result.output
    again = run("style", report, "--dry-run")
    assert again.exit_code == 0, again.output

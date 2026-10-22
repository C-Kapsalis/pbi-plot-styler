"""filter-panel --fix: acts only on a PNL001 report; messages, guard, encoding."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from canvas_variants import MAIN, VARIANTS, _edit, _load, _save, _v
from cli_helpers import copy_fixture, run

REPORT = "-Report.Report"


@pytest.fixture
def client(tmp_path: Path) -> Path:
    return copy_fixture("universal", tmp_path)


def _snapshot(root: Path) -> dict[str, bytes]:
    return {str(p): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def _named_master(client: Path) -> list[Path]:
    return [p for p in (client / REPORT / "definition" / "pages").glob("*/visuals/*/visual.json")
            if (_load(p).get("visualGroup") or {}).get("displayName") == "y_filters_group"]


def _add_subgroup(client: Path, parent: str) -> None:
    """A group nested under the master that covers the same filter tables."""
    _save(_v(client, "sub_filters"), {"name": "sub_filters", "parentGroupName": parent,
                                      "position": {"x": 0, "y": 0, "z": 0, "width": 1, "height": 1},
                                      "visualGroup": {"displayName": "Sub filters", "groupMode": "ScaleMode"}})
    for n in range(3, 7):
        _edit(_v(client, f"y_selector_{n}_slicer"), lambda x: x.update(parentGroupName="sub_filters"))


def test_a_compliant_report_with_a_nested_subgroup_is_left_alone(client):
    _add_subgroup(client, "y_filters_group")
    before = _snapshot(client)
    result = run("check", client / REPORT, "--rule", "filter-panel", "--fix")
    assert result.exit_code == 0, result.output
    assert _snapshot(client) == before
    assert "already present" in result.output
    assert len(_named_master(client)) == 1


def test_a_master_in_a_hash_named_folder_is_left_alone(client):
    master = _v(client, "y_filters_group")
    data = _load(master)
    data["name"] = "9a8b7c6d5e4f3a2b1c0d"
    shutil.rmtree(master.parent)
    _save(_v(client, "9a8b7c6d5e4f3a2b1c0d"), data)
    for path in (client / REPORT / "definition" / "pages" / MAIN / "visuals").glob("*/visual.json"):
        if _load(path).get("parentGroupName") == "y_filters_group":
            _edit(path, lambda x: x.update(parentGroupName="9a8b7c6d5e4f3a2b1c0d"))
    _add_subgroup(client, "9a8b7c6d5e4f3a2b1c0d")
    before = _snapshot(client)
    result = run("check", client / REPORT, "--rule", "filter-panel", "--fix")
    assert result.exit_code == 0, result.output
    assert _snapshot(client) == before
    assert len(_named_master(client)) == 1


def test_the_change_line_names_the_old_display_name_and_the_tables(client):
    VARIANTS["rule8-renamed"](client)
    result = run("check", client / REPORT, "--rule", "filter-panel", "--fix")
    assert result.exit_code == 0, result.output
    line = next(ln for ln in result.output.splitlines() if "renamed group" in ln)
    assert "'g1'" in line and "'Filters'" in line
    assert "y-Selector 3, y-Selector 4, y-Selector 5, y-Selector 6" in line


def test_a_non_group_visual_is_never_made_the_master(client):
    VARIANTS["rule8-renamed"](client)
    # turn g1 into a plain visual: it can no longer be the master
    _edit(_v(client, "g1"), lambda d: (d.pop("visualGroup"), d.update(visual={"visualType": "shape"})))
    before = _snapshot(client)
    result = run("check", client / REPORT, "--rule", "filter-panel", "--fix")
    assert _snapshot(client) == before, result.output
    assert "no group covers" in result.output


def test_the_fix_writes_non_ascii_text_escaped(client):
    VARIANTS["rule8-renamed"](client)
    _edit(_v(client, "y_selector_3_slicer"), lambda d: d.update(title="Περιοχή"))
    assert run("check", client / REPORT, "--rule", "filter-panel", "--fix").exit_code == 0
    raw = _v(client, "y_selector_3_slicer").read_text(encoding="utf-8")
    assert "Περιοχή" not in raw and "\\u03a0" in raw
    assert json.loads(raw)["title"] == "Περιοχή"

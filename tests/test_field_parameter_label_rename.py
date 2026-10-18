"""F-field-parameter-label-rename: ``rename-label CLIENT_DIR --pair OLD NEW [--apply]``.

New tests (no original pytest test). Fixture ``fixtures/label-rename/client``:
label ``"Cost/ New Customer"`` in ``x-Selector 1`` and in two bookmarks;
``"Cohort Cost/ New Customer"`` (selector row and a card label) must stay.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ported_helpers import copy_fixture, run

OLD, NEW = "Cost/ New Customer", "CAC"
LONGER = "Cohort Cost/ New Customer"


@pytest.fixture
def client(tmp_path: Path) -> Path:
    return copy_fixture("label-rename/client", tmp_path)


def _snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def _changed(before: dict, after: dict) -> set[str]:
    return {k for k in before if before[k] != after[k]}


def test_dry_run_writes_nothing(client):
    before = _snapshot(client)
    result = run("rename-label", client, "--pair", OLD, NEW)
    assert result.exit_code == 0, result.output
    assert "DRY RUN" in result.output
    assert _snapshot(client) == before


def test_apply_rewrites_three_files(client):
    before = _snapshot(client)
    result = run("rename-label", client, "--pair", OLD, NEW, "--apply")
    assert result.exit_code == 0, result.output
    assert "APPLIED" in result.output
    after = _snapshot(client)
    changed = _changed(before, after)
    assert changed == {
        "Growth.SemanticModel/definition/tables/x-Selector 1.tmdl",
        "Growth.Report/definition/bookmarks/b1b1b1b1b1b1b1b1b1b1.bookmark.json",
        "Growth.Report/definition/bookmarks/b2b2b2b2b2b2b2b2b2b2.bookmark.json",
    }
    for rel in changed:
        assert rel in result.output  # touched paths are listed relative to the client folder
        text = after[rel].decode("utf-8")
        assert f'"{OLD}"' not in text and f'"{NEW}"' in text


def test_longer_label_containing_old_is_untouched(client):
    assert run("rename-label", client, "--pair", OLD, NEW, "--apply").exit_code == 0
    selector = (client / "Growth.SemanticModel/definition/tables/x-Selector 1.tmdl").read_text(encoding="utf-8")
    assert f'"{LONGER}"' in selector
    card = next(client.rglob("card01/visual.json")).read_text(encoding="utf-8")
    assert f'"{LONGER}"' in card


def test_longest_old_label_is_applied_first(client):
    # "Cost/ New Customer" (longer) goes first and becomes "CAC"; then "CAC" -> "Acquisition Cost"
    result = run("rename-label", client, "--pair", "CAC", "Acquisition Cost", "--pair", OLD, "CAC", "--apply")
    assert result.exit_code == 0, result.output
    selector = (client / "Growth.SemanticModel/definition/tables/x-Selector 1.tmdl").read_text(encoding="utf-8")
    assert '"Acquisition Cost"' in selector
    assert '"CAC"' not in selector


def test_a_replacement_that_breaks_json_aborts(client):
    bookmark = client / "Growth.Report/definition/bookmarks/b1b1b1b1b1b1b1b1b1b1.bookmark.json"
    before = bookmark.read_bytes()
    result = run("rename-label", client, "--pair", OLD, 'Bad"Label', "--apply")
    assert result.exit_code != 0
    assert bookmark.read_bytes() == before

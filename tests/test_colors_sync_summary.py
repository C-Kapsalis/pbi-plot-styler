"""SCX48: the colours sync summary, the file list and the dry-run note.

The closing counts are the original's:

    would write <f> file(s): <r> colour entry/entries rewritten, <a> added
       <path>
       ...

    (dry run -- pass --apply to write)

With `--apply` the first line begins `wrote` and there is no note. The
note appears only in a dry run that has at least one changed file. Each
path line has three leading spaces.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cli_helpers import copy_fixture, run


@pytest.fixture
def shop(tmp_path: Path) -> Path:
    return copy_fixture("color-sync", tmp_path)


def _args(shop: Path) -> list:
    return ["--report", shop / "Shop.Report", "--model", shop / "Shop.SemanticModel"]


def test_a_dry_run_lists_the_files_and_the_note(shop):
    """SCX48: the block, the paths and the note."""
    result = run("colors", "sync", *_args(shop))
    assert result.exit_code == 1, result.output
    out = result.output
    assert "would write " in out, out
    assert "colour entry/entries rewritten" in out, out
    assert "(dry run -- pass --apply to write)" in out, out
    for line in out.splitlines():
        if line.startswith("   ") and not line.startswith("    "):
            assert line.strip(), "an empty path line"


def test_an_applied_run_says_wrote_and_has_no_note(shop):
    """SCX48: with `--apply` the note is gone."""
    result = run("colors", "sync", *_args(shop), "--apply")
    out = result.output
    assert "wrote " in out, out
    assert "(dry run -- pass --apply to write)" not in out, out


def test_nothing_to_do_says_zero(shop):
    """SCX48: the counts are zero when there is nothing to do."""
    run("colors", "sync", *_args(shop), "--apply")
    result = run("colors", "sync", *_args(shop))
    assert "would write 0 file(s): 0 colour entry/entries rewritten, 0 added" \
        in result.output, result.output

"""
Layer 3.5: the report-layer renamer must see EVERY binding form (PBI#505)

A measure is referenced from `visual.json` / `*.bookmark.json` in four distinct
shapes, and `rename_measure` must rewrite all four. Until 2026-08-17
it saw only three, and the one it missed — `metadata` — was the DOMINANT form:
measured on spinout_05_db for the PBI#494 `LTV` family, 144 of 208 bindings were
`metadata`, against 20 `Measure.Property`, 12 `queryRef`, 12 `nativeQueryRef`.

Why this is a p0 and not a nice-to-have: a renamer blind to a form does not
error. It rewrites the forms it knows, returns a plausible non-zero count, and
leaves the rest bound to a name that no longer exists — a broken visual with a
green run behind it. That is the "answers instead of failing" class, sitting
inside the remediation toolchain, which is the code least likely to be doubted.

Two invariants, and the second is the one that lets the first rot quietly:

1. `rewrite_tree` handles all four forms.
2. `count_tree` counts EXACTLY what `rewrite_tree` rewrites. They diverged before —
   `count_tree` saw only `Measure.Property` — so a dry-run count structurally could
   not predict the apply. A fixture that only tested (1) would have stayed green
   through that.
"""
from __future__ import annotations

import json

import pytest

from pbi_plot_styler.rename import count_measure_refs, count_tree, rename_measure, rewrite_tree

OLD = "Observed LTV (maturation)"
NEW = "Observed {N}month Value (maturation)"
TABLE = "#Backend Measures"

# one node per binding form, each holding exactly one reference to OLD
FORMS = {
    "Measure.Property": {
        "Measure": {
            "Expression": {"SourceRef": {"Entity": TABLE}},
            "Property": OLD,
        }
    },
    "queryRef": {"queryRef": f"{TABLE}.{OLD}"},
    "nativeQueryRef": {"nativeQueryRef": OLD},
    "metadata": {"selector": {"metadata": f"{TABLE}.{OLD}"}},
}


@pytest.mark.p0
@pytest.mark.layer3_5
@pytest.mark.parametrize("form", sorted(FORMS))
def test_rewrite_handles_every_binding_form(form):
    """Each of the four forms must be rewritten, not silently skipped."""
    node = json.loads(json.dumps(FORMS[form]))
    n = rewrite_tree(node, OLD, NEW)
    assert n == 1, (
        f"binding form {form!r} was NOT rewritten. A renamer blind to a form "
        f"reports success and leaves the visual bound to a dead name."
    )
    assert OLD not in json.dumps(node)
    assert NEW in json.dumps(node)


@pytest.mark.p0
@pytest.mark.layer3_5
@pytest.mark.parametrize("form", sorted(FORMS))
def test_count_agrees_with_rewrite(form):
    """`count_tree` must predict `rewrite_tree` exactly, or a dry run means nothing."""
    node = FORMS[form]
    counted = count_tree(json.loads(json.dumps(node)), OLD)
    rewritten = rewrite_tree(json.loads(json.dumps(node)), OLD, NEW)
    assert counted == rewritten == 1, (
        f"count/rewrite disagree on {form!r}: counted {counted}, "
        f"rewrote {rewritten}. A dry-run count that under-reports is worse "
        f"than none — it is trusted."
    )


@pytest.mark.p0
@pytest.mark.layer3_5
def test_all_forms_together_on_a_real_file(tmp_path):
    """End-to-end through the file walker, all four forms in one visual."""
    visual = tmp_path / "definition" / "pages" / "p1" / "visuals" / "v1"
    visual.mkdir(parents=True)
    (visual / "visual.json").write_text(
        json.dumps({"nodes": list(FORMS.values())}, indent=2), encoding="utf-8")

    roots = [tmp_path]
    assert count_measure_refs(roots, OLD) == 4
    assert rename_measure(roots, OLD, NEW) == 4
    assert count_measure_refs(roots, OLD) == 0

    text = (visual / "visual.json").read_text(encoding="utf-8")
    assert OLD not in text
    assert text.count(NEW) == 4


@pytest.mark.p0
@pytest.mark.layer3_5
def test_column_bindings_are_never_touched():
    """The original guarantee still holds: Column nodes stay untouched even
    when a column shares a measure's name."""
    node = {"Column": {"Expression": {"SourceRef": {"Entity": TABLE}},
                       "Property": OLD}}
    assert rewrite_tree(node, OLD, NEW) == 0
    assert node["Column"]["Property"] == OLD

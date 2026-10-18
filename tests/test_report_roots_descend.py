"""Report-root discovery must descend, or every report-layer count silently lies.

Ported from the author's layer-3.5 suite. A client may nest report trees in
subfolders (for example `spinout_10_db/Finalized/`). A model-sibling
`glob("*.Report")` misses them, and because callers gate destructive work on
the COUNTS these helpers return, a shallow glob answers 0 for a measure that
nested reports still render. Stand-in: tests/fixtures/spinout_10_db
(Growth.SemanticModel, -Report.Report, Finalized/Weekly.Report).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

import pbi_plot_styler
from pbi_plot_styler.rename import report_roots

pytestmark = [pytest.mark.p1, pytest.mark.layer3_5]

FIXTURES = Path(__file__).parent / "fixtures"

# A shallow glob for report roots. Anything matching this is a latent
# under-scope: it will silently skip nested report trees.
_SHALLOW_RX = re.compile(r'(?<!r)glob\(\s*["\']\*\.Report')


def test_iter_report_roots_descends_into_nested_report_trees():
    """spinout_10_db's Finalized/ reports must be reachable from its model."""
    model = FIXTURES / "spinout_10_db" / "Growth.SemanticModel"
    if not model.is_dir():
        pytest.skip("spinout_10_db/Growth.SemanticModel not present in this checkout")

    roots = report_roots(model)
    nested = [r for r in roots if "Finalized" in str(r)]

    # Control first: prove the instrument finds the easy case.
    siblings = [r for r in roots if r.parent == model.parent]
    assert siblings, "found no model-sibling reports at all - call is broken, not the data"

    assert nested, (
        "report_roots returned no spinout_10_db/Finalized report root.\n"
        f"roots returned: {[str(r) for r in roots]}"
    )


def test_no_shallow_report_glob_in_scripts():
    """No call site in the tool's own package may discover reports with a
    model-sibling-only glob (the original linted its scripts/ folder)."""
    package = Path(pbi_plot_styler.__file__).parent
    offenders = []
    for py in sorted(package.rglob("*.py")):
        for i, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
            if _SHALLOW_RX.search(line):
                offenders.append(f"{py.relative_to(package)}:{i}: {line.strip()}")

    assert not offenders, (
        "Shallow `glob(\"*.Report\")` found - use `rglob` so nested report trees "
        "are included.\n  " + "\n  ".join(offenders)
    )

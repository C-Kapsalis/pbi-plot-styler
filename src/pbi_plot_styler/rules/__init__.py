"""Convention rules for ``check --rule SLUG``.

Each rule is a read-only check plus, for some, a fixer. A rule reports
findings through the same :class:`~pbi_plot_styler.check.ReportContext` the
integrity checks use, so ids, baselines, JSON output and exit codes behave
identically. Rules that do not apply to a report (no y-combo groups, no
paired model, an ambiguous placeholder) add a note to ``skipped`` instead of
passing silently.

``integrity`` is the default rule: the checks ``check`` has always run.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..canvas import Bookmark, ReportIndex, Settings, load_bookmarks
from ..check import ReportContext, fix_report, run_integrity


class RuleError(RuntimeError):
    """A rule cannot run on this report (exit 2, nothing written)."""


@dataclass
class RuleContext(ReportContext):
    """A report context with the canvas settings and lazily loaded indexes."""

    settings: Settings = field(default_factory=Settings)
    options: dict[str, Any] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)
    #: why the paired model failed to load, when it did (MDL001).
    model_error: str | None = None
    #: rule slug -> number of components the rule judged (for --summary).
    checked: dict[str, int] = field(default_factory=dict)
    #: rule slug -> {what was judged: count}, printed after the findings.
    details: dict[str, dict[str, int]] = field(default_factory=dict)
    _index: ReportIndex | None = None
    _bookmarks: list[Bookmark] | None = None

    @property
    def index(self) -> ReportIndex:
        if self._index is None:
            self._index = ReportIndex.load(self.report_dir)
        return self._index

    @property
    def bookmarks(self) -> list[Bookmark]:
        if self._bookmarks is None:
            self._bookmarks = load_bookmarks(self.report_dir)
        return self._bookmarks

    @property
    def label(self) -> str:
        return self.rel(self.report_dir)

    def missing_model(self, rule: str) -> None:
        """Note that ``rule`` was skipped for want of a usable model."""
        if self.model_error:
            self.skip(f"{rule}: the paired semantic model could not be loaded "
                      f"(see MDL001)")
        else:
            self.skip(f"{rule}: no paired semantic model")

    def skip(self, message: str) -> None:
        note = f"{self.label}: {message}"
        if note not in self.skipped:
            self.skipped.append(note)


#: A fixer returns ``(path, description)`` for every change it wrote.
Fixer = Callable[[RuleContext], list[tuple[Path, str]]]


@dataclass(frozen=True)
class Rule:
    slug: str
    title: str
    ids: tuple[str, ...]
    check: Callable[[RuleContext], None]
    fix: Fixer | None = None
    #: raises :class:`RuleError` when the fixer could not run on a report;
    #: called for every report before any fixer writes.
    prepare: Callable[[RuleContext], Any] | None = None
    #: ids whose error findings make the rule non-compliant in --summary.
    critical: tuple[str, ...] = ()


def _integrity_fix(ctx: RuleContext) -> list[tuple[Path, str]]:
    fixed, refused = fix_report(ctx.report_dir)
    ctx.options.setdefault("refused", []).extend(refused)
    return fixed


def _registry() -> dict[str, Rule]:
    from . import answers, category, format_selector, gates, layout, panel, placeholders

    rules = [
        Rule("integrity", "bindings, bookmarks, field-parameter slots, theme files",
             ("JSN001", "BND001", "BND002", "BMK001", "BMK002", "BMK003", "BMK004",
              "BMK005", "FPM001", "FPM002", "THM001"),
             run_integrity, _integrity_fix),
        Rule("slicer-gates", "selector slicers carry an active f-Slicer gate",
             ("GAT001", "GAT002"), gates.check_slicer_gates, gates.fix_slicer_gates,
             critical=("GAT001", "GAT002")),
        Rule("slicer-mode-gates", "slicer gates match the slicer mode",
             ("GAT003", "GAT004", "GAT005"), gates.check_mode_gates, gates.fix_mode_gates,
             prepare=gates.gate_host_table),
        Rule("category-filter", "answer bookmarks set the analysis category",
             ("CAT001",), category.check_category_filter, critical=("CAT001",)),
        Rule("theme", "theme collection present, no hex literals",
             ("THM002", "THM003", "THM004", "THM005", "THM006"), layout.check_theme,
             critical=("THM002", "THM004")),
        Rule("visual-position", "every visual has an x and y position",
             ("POS001",), layout.check_positions),
        Rule("y-combo", "y-combo groups are named and parented",
             ("YCG001", "YCG002"), layout.check_y_combo),
        Rule("filter-panel", "the filter slicers live in the master group",
             ("PNL001", "PNL002"), panel.check_filter_panel, panel.fix_filter_panel,
             critical=("PNL001",)),
        Rule("format-selector", "a hidden, locked filter selects the Format item",
             ("FMT001",), format_selector.check_format_selector,
             format_selector.fix_format_selector),
        Rule("stale-placeholders", "saved state names a placeholder its axis offers",
             ("PLH001",), placeholders.check_placeholders, placeholders.fix_placeholders),
        Rule("answer-bookmarks", "whole-page answer bookmarks and their page",
             ("ABK000", "ABK001", "ABK003", "ABK004", "ABK005", "ABK006", "ABK007",
              "ABK008", "ABK009", "ABK010", "PGW001", "PGW002", "JSN001"),
             answers.check_answer_bookmarks),
        Rule("bookmark-literals", "picker literals are rows of their selector",
             ("BML001", "BML002", "JSN001"), answers.check_bookmark_literals),
    ]
    return {rule.slug: rule for rule in rules}


_RULES: dict[str, Rule] | None = None


def rules() -> dict[str, Rule]:
    """slug -> :class:`Rule`, in documentation order."""
    global _RULES
    if _RULES is None:
        _RULES = _registry()
    return _RULES


#: Findings a baseline can never accept: they mean the run checked nothing.
UNBASELINABLE = frozenset({"ABK000"})

#: The four foundation rules summarised by ``check --summary``.
SUMMARY_RULES = ("slicer-gates", "category-filter", "theme", "filter-panel")


# -- file writing shared by the fixers ------------------------------------------
def rewrite_json(path: Path, data: Any, *, ascii_only: bool = False) -> bool:
    """Write ``data`` back to ``path`` as 2-space JSON when it changed.

    The file keeps its own conventions: a UTF-8 BOM, CRLF line endings and
    the presence or absence of a final newline. Non-ASCII text is written as
    is, or as ``\\u`` escapes with ``ascii_only``. Returns whether it wrote.
    """
    raw = path.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    old_text = raw.decode("utf-8-sig")
    try:
        if json.loads(old_text) == data:
            return False
    except json.JSONDecodeError:
        pass
    text = json.dumps(data, indent=2, ensure_ascii=ascii_only)
    if old_text.endswith("\n"):
        text += "\n"
    if "\r\n" in old_text:
        text = text.replace("\n", "\r\n")
    path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8"))
    return True


#: One-line remediation per finding id (``--summary`` and its JSON ``fix``).
FIX_HINTS = {
    "JSN001": "repair or re-save the file so it parses as JSON",
    "MDL001": "repair the semantic model so it loads, or pass --model",
    "BND001": "rebind the field to one the model declares, or restore the model object",
    "BND002": "update the queryRef / metadata string to a field the model declares",
    "BMK001": "run check --fix (it removes the unknown options keys)",
    "BMK002": "run check --fix (it converts the string integers)",
    "BMK003": "re-capture the bookmark on an existing page, or delete it",
    "BMK004": "re-capture the bookmark without the deleted visual",
    "BMK005": "remove the bookmarks.json entry, or restore the bookmark file",
    "FPM001": "give each field parameter its own slot range in the page's visual.json",
    "FPM002": "shrink the slot range to the projections the well holds",
    "THM001": "restore the theme file or remove its reference from report.json",
    "GAT001": "run check --rule slicer-gates --fix to add the f-Slicer gate filter",
    "GAT002": "run check --rule slicer-gates --fix, or re-capture the bookmark",
    "GAT003": "run check --rule slicer-mode-gates --fix to write the gate for the slicer's mode",
    "GAT004": "run check --rule slicer-mode-gates --fix to repoint the gate at the declaring table",
    "GAT005": "run check --rule slicer-mode-gates --fix to repoint the stale gate reference",
    "CAT001": "re-capture the bookmark with the analysis-category filter set",
    "THM002": "add a theme collection (base and custom theme) to report.json",
    "THM003": "add a custom theme to the report",
    "THM004": "replace the hex colour literals in report.json with theme colours",
    "THM005": "add a base or custom theme to the report",
    "THM006": "restore the missing theme file",
    "POS001": "give the visual an x and y position in its visual.json",
    "YCG001": "rename the group to y<N>_combo_group",
    "YCG002": "move the member into its y<N>_combo_group",
    "PNL001": "run check --rule filter-panel --fix to name the master group",
    "PNL002": "turn y_filters_group into a group visual holding the filter slicers",
    "FMT001": "run check --rule format-selector --fix to write the Format filter",
    "PLH001": "run check --rule stale-placeholders --fix to repoint the placeholder",
    "ABK000": "set [answer_bookmarks] prefixes to the answer bookmarks' display-name prefixes",
    "ABK001": "set options.targetVisualNames to [] (re-capture with no visual selected)",
    "ABK003": "re-capture the bookmark with the matrix visible",
    "ABK004": "rebuild the bookmark with bookmarks build so the matrix rows are its own",
    "ABK005": "rebuild the bookmark with bookmarks build (no active Values, no expansion states)",
    "ABK006": "select at least one field in the picker and re-capture, or rebuild the bookmark",
    "ABK007": "pin the analysis-category filter to a value and re-capture",
    "ABK008": "add the bookmark to a Submenu group in bookmarks.json",
    "ABK009": "rebuild the bookmark with bookmarks build so the slot map matches the picks",
    "ABK010": "mirror each row field into a row dropdown, or rebuild the bookmark",
    "PGW001": "remove the raw measure from the page's parameter well (fix the page first)",
    "PGW002": "point the navigator at an existing bookmark (fix the page first)",
    "BML001": "pick the field in the selector that offers it, or register it there",
    "BML002": "register the field in a field parameter, or pick a registered one",
}


def fix_hint(check_id: str) -> str:
    """Where and how to fix a finding with id ``check_id``."""
    return FIX_HINTS.get(check_id, "see docs/convention-rules.md")

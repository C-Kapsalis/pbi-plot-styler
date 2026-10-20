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
              "ABK008", "ABK009", "ABK010", "PGW001", "PGW002"),
             answers.check_answer_bookmarks),
        Rule("bookmark-literals", "picker literals are rows of their selector",
             ("BML001", "BML002"), answers.check_bookmark_literals),
    ]
    return {rule.slug: rule for rule in rules}


_RULES: dict[str, Rule] | None = None


def rules() -> dict[str, Rule]:
    """slug -> :class:`Rule`, in documentation order."""
    global _RULES
    if _RULES is None:
        _RULES = _registry()
    return _RULES


#: The four foundation rules summarised by ``check --summary``.
SUMMARY_RULES = ("slicer-gates", "category-filter", "theme", "filter-panel")


# -- file writing shared by the fixers ------------------------------------------
def rewrite_json(path: Path, data: Any) -> bool:
    """Write ``data`` back to ``path`` as 2-space JSON when it changed.

    The file keeps its own conventions: a UTF-8 BOM, CRLF line endings and
    the presence or absence of a final newline. Returns whether it wrote.
    """
    raw = path.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    old_text = raw.decode("utf-8-sig")
    try:
        if json.loads(old_text) == data:
            return False
    except json.JSONDecodeError:
        pass
    text = json.dumps(data, indent=2, ensure_ascii=False)
    if old_text.endswith("\n"):
        text += "\n"
    if "\r\n" in old_text:
        text = text.replace("\n", "\r\n")
    path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8"))
    return True

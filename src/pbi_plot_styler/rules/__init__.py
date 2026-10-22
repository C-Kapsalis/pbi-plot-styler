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


class RuleAbort(RuleError):
    """A rule cannot run, and says so in its own words (exit 2).

    The message is printed as it stands: no `Error: ` prefix.
    """


def user_path(ctx: "RuleContext", report_dir: Path) -> str:
    """The report folder as the user named it.

    The PATH argument when the report is the PATH, otherwise the PATH
    joined with the report's own path under it.
    """
    base = ctx.options.get("check_path")
    if base is None:
        return ctx.rel(report_dir)
    if report_dir == base:
        return base.as_posix()
    try:
        return (base / report_dir.relative_to(base)).as_posix()
    except ValueError:
        return report_dir.as_posix()


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
    #: ids that count toward the rule's --summary row (empty: all ``ids``).
    summary_ids: tuple[str, ...] = ()
    #: keep findings in the order the rule found them (not sorted by file).
    ordered: bool = False
    #: text output: ``(new findings, counts, framing, values) -> lines``.
    render: Callable[..., list[str]] | None = None
    #: text output of a fix run: ``(ctx, changes) -> lines``.
    render_fix: Callable[..., list[str]] | None = None
    #: the rule's own lines replace the generic ``fixed`` lines.
    replace_fix_lines: bool = False
    #: the closing lines of a fix run: ``(contexts) -> lines``.
    fix_summary: Callable[..., list[str]] | None = None

    @property
    def summarised(self) -> tuple[str, ...]:
        return self.summary_ids or self.ids


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
             critical=("GAT001", "GAT002"), render=gates.render_slicer_gates,
             render_fix=gates.render_slicer_gates_fix, replace_fix_lines=True,
             fix_summary=gates.slicer_gates_fix_summary),
        Rule("slicer-mode-gates", "slicer gates match the slicer mode",
             ("GAT003", "GAT004", "GAT005"), gates.check_mode_gates, gates.fix_mode_gates,
             prepare=gates.gate_host_table, render=gates.render_mode_gates,
             render_fix=gates.render_mode_gates_fix, replace_fix_lines=True,
             fix_summary=gates.mode_gates_fix_summary, ordered=True),
        Rule("category-filter", "answer bookmarks set the analysis category",
             ("CAT001",), category.check_category_filter, critical=("CAT001",),
             render=category.render_category_filter),
        Rule("theme", "theme collection present, no hex literals",
             ("THM002", "THM003", "THM004", "THM005", "THM006"), layout.check_theme,
             critical=("THM002", "THM004"), summary_ids=("THM002", "THM003", "THM004"),
             render=layout.render_theme),
        Rule("visual-position", "every visual has an x and y position",
             ("POS001",), layout.check_positions, render=layout.render_positions),
        Rule("y-combo", "y-combo groups are named and parented",
             ("YCG001", "YCG002"), layout.check_y_combo, render=layout.render_y_combo),
        Rule("filter-panel", "the filter slicers live in the master group",
             ("PNL001", "PNL002"), panel.check_filter_panel, panel.fix_filter_panel,
             critical=("PNL001",), render=panel.render_filter_panel,
             render_fix=panel.render_filter_panel_fix,
             fix_summary=panel.filter_panel_fix_summary),
        Rule("format-selector", "a hidden, locked filter selects the Format item",
             ("FMT001",), format_selector.check_format_selector,
             format_selector.fix_format_selector,
             render=format_selector.render_format_selector,
             render_fix=format_selector.render_format_selector_fix,
             fix_summary=format_selector.format_selector_fix_summary),
        Rule("stale-placeholders", "saved state names a placeholder its axis offers",
             ("PLH001",), placeholders.check_placeholders, placeholders.fix_placeholders,
             ordered=True, render=placeholders.render_placeholders),
        Rule("answer-bookmarks", "whole-page answer bookmarks and their page",
             ("ABK000", "ABK001", "ABK003", "ABK004", "ABK005", "ABK006", "ABK007",
              "ABK008", "ABK009", "ABK010", "PGW001", "PGW002", "JSN001"),
             answers.check_answer_bookmarks, ordered=True, render=render_answers),
        Rule("bookmark-literals", "picker literals are rows of their selector",
             ("BML001", "BML002", "JSN001"), answers.check_bookmark_literals, ordered=True,
             render=render_literals),
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


#: The four foundation rules as the earlier report named them: the rule
#: number, the rule name and the finding type of each id.
RULE_REPORT = {
    "slicer-gates": (1, "Field Parameter f-Slicer Filters"),
    "category-filter": (3, "Analysis Category Filter Required"),
    "theme": (6, "ThemeDataColor Integration"),
    "filter-panel": (8, "y_filters_group Master Container"),
}

#: finding id -> (type, description, component). A description of ``None``
#: is taken from the finding's message, without its expected/actual tail.
FINDING_TYPES = {
    "GAT001": ("missing_f_slicer_gate",
                "field-parameter slicer not gated on f-Slicer measure", None),
    "GAT002": (None, None, None),
    "CAT001": ("missing_analysis_category",
                "Page-level bookmark has no Analysis Category filter", None),
    "THM002": ("missing_theme_collection",
               "Report missing themeCollection configuration", "report"),
    "THM003": ("missing_custom_theme",
               "No custom theme defined - may use hardcoded colors", "report"),
    "THM004": ("hardcoded_hex_colors", None, "report.json"),
    "THM005": (None, "Report has no theme configuration. Without a base or custom "
                     "theme, ThemeDataColor references cannot resolve and visuals "
                     "fall back to Power BI defaults.", "report"),
    "THM006": (None, "Theme collection is incomplete - missing: baseTheme, "
                     "customTheme. Reports must declare both baseTheme and "
                     "customTheme.", "report"),
    "PNL001": ("missing_master_container",
               "No y_filters_group master container found", "report"),
    "PNL002": ("wrong_container_type",
               "y_filters_group should be a group container, not specific visual",
               None),
}


def finding_type(check_id: str) -> tuple[str | None, str | None, str | None]:
    """``(type, description, component)`` of a finding id."""
    return FINDING_TYPES.get(check_id, (None, None, None))


def rule_result_block(number: int, findings: list, counts: dict, framing, values, *,
                      violations: bool = True, failure: bool = True) -> list[str]:
    """The result block and the failure block of one foundation rule.

    The result block counts the components the rule judged; the failure
    block lists the error findings, once. The findings themselves keep the
    lint framing and come first. A summary run prints the compliance
    report instead, so only the findings are printed here.
    """
    lines = [framing(f) for f in findings]
    if values.get("summary"):
        return lines
    checked = counts.get("components", 0)
    critical = [f for f in findings if f.severity == "error"]
    passed = max(checked - len({f.location for f in critical}), 0)
    lines += [
        f"✅ Rule #{number} Validation Results:",
        f"   Components checked: {checked}",
        f"   Components passed: {passed}",
        f"   Compliant: {not critical}",
    ]
    if violations and findings:
        lines.append("")
        lines.append("   Violations found:")
        for finding in findings:
            icon = "\U0001F534" if finding.severity == "error" else "⚠️"
            _kind, description, component = finding_type(finding.check_id)
            if description is None:
                description = finding.message.split(" (Expected:", 1)[0]
            if component is None:
                component = finding.subject
            lines.append(f"   {icon} {component}: {description}")
    if critical and failure:
        lines.append(f"Rule #{number} critical violations found:")
        for finding in critical:
            lines.append(f"  - {finding.subject}: {finding.message}")
    return lines


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
    "GAT001": ("In Power BI Desktop, select this slicer, open the Filters pane, drag "
               "the `f-Slicer` measure (from `f-Filters` or `w-Visuals Filters`) into "
               "'Filters on this visual', and set the condition to >= 1 (or > 0)."),
    "GAT002": "run check --rule slicer-gates --fix, or re-capture the bookmark",
    "GAT003": "run check --rule slicer-mode-gates --fix to write the gate for the slicer's mode",
    "GAT004": "run check --rule slicer-mode-gates --fix to repoint the gate at the declaring table",
    "GAT005": "run check --rule slicer-mode-gates --fix to repoint the stale gate reference",
    "CAT001": ("In Power BI Desktop, with this bookmark active, set the Analysis Category "
               "filter on the page (via the z-Map Dimension-Measure Groupings table), "
               "then UPDATE the bookmark so it captures that state."),
    "THM002": "Add themeCollection with proper theme references",
    "THM003": "Define customTheme to avoid hardcoded color values",
    "THM004": ("Replace each '#RGBHEX' literal in report.json with a ThemeDataColor "
               "reference so customer rebrand flows through. For values that "
               "legitimately need to be literal (e.g. image overlays), move them to "
               "the theme JSON."),
    "THM005": "add a base or custom theme to the report",
    "THM006": "restore the missing theme file",
    "POS001": "give the visual an x and y position in its visual.json",
    "YCG001": "rename the group to y<N>_combo_group",
    "YCG002": "move the member into its y<N>_combo_group",
    "PNL001": ("In Power BI Desktop, select every y{N}_combo_group container, right-click "
               "-> Group, and rename the resulting group's displayName to "
               "'y_filters_group'. This is the master container that panel-toggle "
               "bookmarks bind to and that downstream tooling uses to locate the filter "
               "region."),
    "PNL002": "Convert to group container for proper hierarchy",
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


# -- text output ---------------------------------------------------------------------
#: Guidance printed after a run of new findings of one id (text output).
GUIDANCE: dict[str, tuple[str, ...]] = {
    "ABK001": (
        "options.targetVisualNames must be PRESENT and EMPTY ([]).",
        "A list of visual ids scopes the bookmark to those visuals only, so its",
        "picker selections, page filter, drill level and group visibility are",
        "silently ignored on apply — the menu entry looks clickable and does",
        "nothing. Deleting the key entirely makes it unclickable instead.",
        "Saving a bookmark in the Power BI Service with a visual selected",
        "re-narrows this field, so a workspace round-trip can reintroduce it.",
    ),
    "ABK007": (
        "The z-Map page filter is what makes a field analysis-appropriate: it",
        "narrows the x-/y-Selector pickers to the groups the z-Map declares legal for",
        "that category. Without it the view is not 'an aspect of a category', and",
        "the pickers offer fields whose combination produces meaningless numbers.",
    ),
    "ABK008": (
        "A bookmark not registered under its category's Submenu group exists in",
        "the file tree and is unreachable in the report — no menu entry renders.",
        "Add its `name` to that group's children in bookmarks.json.",
    ),
    "ABK003": (
        "The matrix is isHidden at page level and belongs to no group, so each",
        "bookmark's own capture is the only thing that can show it. Visible ==",
        "captured WITHOUT a display key (the mode enum has no 'visible' member).",
    ),
    "ABK004": (
        "projections are Power BI's persisted RESOLUTION of the field parameters,",
        "so they must equal what this bookmark's own pickers select. A clone that",
        "keeps its base's resolution shows the base's fields in every view — the",
        "{fingerprints} are the fingerprint.",
    ),
    "ABK005": (
        "projections = Rows AND Values; activeProjections = Rows only (the first",
        "field). Values in activeProjections collapses the matrix to one column.",
        "expansionStates pin row expansion against specific fields, so inherited",
        "from a base they point at fields this bookmark does not use.",
    ),
    "ABK009": (
        "The Values well declares SEVERAL field parameters, and",
        "singleVisual.parameters is the slot map: each parameter owns a contiguous",
        "range [index, index+length) of projections.Values, whose contents are the",
        "parameters' selections CONCATENATED in declared order — never",
        "deduplicated, because a slot belongs to exactly one parameter.",
        "A pick outside its parameter's range renders NOTHING: the well lists the",
        "parameter, the slicer shows the selection, the literal validator is green,",
        "and the matrix simply has no column for it.",
        "Fix: rebuild projections + parameters from the picker selections (what",
        "`pbi-plot-styler bookmarks build` does), or distribute the measure set so",
        "one measure is not selected in two parameters.",
    ),
    "ABK010": (
        "Owner rule: every dimension the matrix breaks rows by must also be",
        "selected in one of the {dropdowns} dropdown filters, so a reader can",
        "narrow to a value of it. A breakdown you cannot filter is half a view.",
        "`pbi-plot-styler bookmarks build` mirrors Rows into the dropdowns automatically.",
    ),
    "PGW001": (
        "A projection in the PAGE definition renders in EVERY bookmark and no",
        "bookmark can remove it. Fix it in",
        "definition/pages/<page>/visuals/<visual>/visual.json, not in a bookmark.",
        "Exception: '{slot_table}' placeholders are the template",
        "reserving its parameter slots and are expected.",
    ),
    "PGW002": (
        "Deleting or re-emitting a bookmark under a new name leaves the",
        "navigator's selectedBookmark dangling and the strip renders a dead entry.",
    ),
}
_SLOTS_GUIDANCE = (
    "Each parameter owns [index, index+length) of the well's projections.",
    "Where two claim the same slot the LATER declaration wins it, so the",
    "earlier parameter's picks render in NO bookmark — and because it is page",
    "level, every bookmark is wrong identically, which reads like a bookmark",
    "bug and is not one.",
    "This is NOT a rule that indexes start at 0 and run contiguously: a fixed",
    "projection may own a slot, as the z_space template visual does.",
)
GUIDANCE["FPM001"] = GUIDANCE["FPM002"] = _SLOTS_GUIDANCE


def guided_lines(findings: list, framing: Callable[[Any], str],
                 values: dict[str, str] | None = None) -> list[str]:
    """Finding lines; a run of one id with guidance gets a header and the guidance."""
    values = values or {}
    lines: list[str] = []
    i = 0
    while i < len(findings):
        check_id = findings[i].check_id
        j = i
        while j < len(findings) and findings[j].check_id == check_id:
            j += 1
        guidance = GUIDANCE.get(check_id)
        if guidance:
            lines.append(f"{check_id} — NEW finding(s), not in the baseline:")
        lines += [framing(f) for f in findings[i:j]]
        if guidance:
            lines.append("")
            lines += [line.format(**values) if "{" in line else line for line in guidance]
        i = j
    return lines


def render_answers(findings: list, counts: dict, framing, values: dict) -> list[str]:
    lines = [f"bookmarks tested: {counts.get('answer bookmarks', 0)} | failures: {len(findings)}"]
    if not findings:
        lines.append("  all visual-level checks pass (ABK001, ABK003-ABK010, PGW001-PGW002)")
    return lines + guided_lines(findings, framing, values)


def render_literals(findings: list, counts: dict, framing, values: dict) -> list[str]:
    lines = [f"bookmarks checked: {counts.get('bookmarks checked', 0)} | literals OK: "
             f"{counts.get('literals OK', 0)} | UNREGISTERED: {counts.get('UNREGISTERED', 0)}"]
    return lines + [framing(f) for f in findings]

"""Command-line interface for pbi-plot-styler.

Commands: ``style`` (the default, so ``pbi-plot-styler REPORT_DIR`` keeps
working exactly as before), ``check`` (integrity checks plus the canvas
convention rules, with optional fixers), ``colors sync|reset``,
``bookmarks build``, ``rename-measure`` and ``rename-label``.

Style notes (deliberate deviations from the Heroku CLI style guide):
help descriptions are complete sentences with sentence-case capitalization
and terminal periods, following the Click ecosystem convention rather than
Heroku's lowercase-no-period rule. Errors go to stderr and exit codes are
CI-grade (0 ok / 1 drift or findings / 2 error), which the guide and the
docs agree on.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from . import __version__
from .check import (
    CHECKS,
    Finding,
    load_baseline,
    write_baseline,
)
from .canvas import Settings, SettingsError, load_settings
from .config import DEFAULT_CONFIG_FILENAME, ConfigError, build_config
from .report import (
    RestyleInvariantError,
    VisualChange,
    apply_changes,
    discover_reports,
    enclosing_report,
    is_report_dir,
    plan_changes,
    report_model_name,
    resolve_model_dir,
    write_zip,
)
from .bookmark_builder import TOP_LEVEL, BuildError, build_bookmarks, load_builder_settings
from .colors import ColorOptions, PaletteError
from .colors import reset as color_reset
from .colors import sync as color_sync
from .labels import LabelRenameError, rename_labels
from .rename import count_measure_refs, rename_measure, report_roots
from .rules import SUMMARY_RULES, UNBASELINABLE, RuleContext, RuleError, fix_hint, rules
from .rules.answers import load_display_name_filter
from .tmdl import SemanticModel

EXIT_OK = 0
EXIT_DRIFT = 1
EXIT_ERROR = 2

DEFAULT_COMMAND = "style"


class StylerError(click.ClickException):
    """A fatal error; exits with EXIT_ERROR so CI can tell it from drift."""

    exit_code = EXIT_ERROR


class DefaultCommandGroup(click.Group):
    """A group that runs ``style`` when the first argument is not a command.

    This keeps the classic ``pbi-plot-styler REPORT_DIR [OPTIONS]`` form
    working unchanged. A report folder literally named like a command
    (``check``) must be passed as ``./check`` or after ``style``.
    """

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        group_flags = {"-h", "--help", "--version"}
        if args and args[0] not in self.commands and args[0] not in group_flags:
            args = [DEFAULT_COMMAND, *args]
        return super().parse_args(ctx, args)


@click.group(
    cls=DefaultCommandGroup,
    context_settings={"help_option_names": ["-h", "--help"]},
    no_args_is_help=True,
)
@click.version_option(__version__, prog_name="pbi-plot-styler")
def main() -> None:
    """Style Power BI combo charts from their field parameters, check PBIP
    reports for broken bindings, bookmarks and canvas conventions, and keep
    colours, bookmarks and renames in step across a report.

    Without a command, `style` runs: `pbi-plot-styler REPORT_DIR` is the
    same as `pbi-plot-styler style REPORT_DIR`.
    """


# -- shared helpers ------------------------------------------------------------
def _discover(path: Path):
    discovery = discover_reports(path)
    for skipped, reason in discovery.skipped:
        click.echo(f"Skipped:  {skipped.relative_to(path).as_posix()} ({reason})", err=True)
    if not discovery.reports:
        raise StylerError(
            f"no *.Report folders found under {path}. Pass a PBIP report "
            f"folder (one containing definition.pbir and definition/pages), "
            f"or a folder that contains one or more of them."
        )
    return discovery


def _parse_pairs(entries: tuple[str, ...], flag: str, example: str) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for entry in entries:
        name, sep, value = entry.rpartition("=")
        if not sep or not name.strip() or not value.strip():
            raise StylerError(
                f"{flag} {entry!r} is not in KEY=VALUE form. For example: "
                f"{flag} {example}."
            )
        pairs[name.strip()] = value.strip()
    return pairs


# -- style ---------------------------------------------------------------------
@main.command(DEFAULT_COMMAND)
@click.argument(
    "report_dir",
    type=click.Path(exists=True, path_type=Path),
)
@click.option(
    "--model",
    "model_dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help="Semantic-model folder, used for every report found. Default: "
    "resolved per report from its definition.pbir (datasetReference.byPath).",
)
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=False, dir_okay=False, path_type=Path),
    default=None,
    help=f"Config file (TOML). Default: ./{DEFAULT_CONFIG_FILENAME} if present.",
)
@click.option(
    "--table",
    "tables",
    multiple=True,
    help="Field-parameter table name or shell-style pattern such as 'x-*' "
    "(repeatable; patterns match the model's tables case-insensitively). "
    "Overrides the default 'x-Plot Specific 1' / 'x-Plot Specific 2' / "
    "'y-Plot Specific' trio.",
)
@click.option(
    "--rename-table",
    "renames",
    multiple=True,
    metavar="OLD=NEW",
    help="Rename one default field-parameter table (repeatable), for "
    "example --rename-table \"y-Plot Specific=Set Lines\". Leaves the "
    "other default table names in place, unlike --table.",
)
@click.option(
    "--visual-type",
    "visual_types",
    multiple=True,
    help="visualType to restyle (repeatable). Default: "
    "lineClusteredColumnComboChart and lineStackedColumnComboChart.",
)
@click.option(
    "--exclude-role",
    "exclude_roles",
    multiple=True,
    help="Query role (repeatable), for example 'Y', whose measures are "
    "excluded from styling on each visual: the measure currently bound to "
    "it, or, when the role is bound through a field parameter, every "
    "measure that parameter offers. Their existing formatting is kept.",
)
@click.option(
    "--line-color",
    default=None,
    help="Hex color for every series line and column fill (for example '#118DFF').",
)
@click.option(
    "--palette",
    "palette",
    multiple=True,
    help="Hex color to add to the palette (repeatable). When set, each "
    "measure gets the color of its stable slot (field-parameter order) "
    "and --line-color is ignored.",
)
@click.option(
    "--color",
    "color_pins",
    multiple=True,
    metavar="TABLE.MEASURE=HEX",
    help="Pin one measure's series color (repeatable), for example "
    "--color \"Sales Measures.Revenue=#7A4419\". Beats the palette, the "
    "theme color, and --line-color.",
)
@click.option(
    "--theme-color-id",
    type=int,
    default=None,
    help="Use the report theme's data color N (0-based) instead of "
    "--line-color, written as a ThemeDataColor so it follows theme changes.",
)
@click.option(
    "--theme-color-percent",
    type=float,
    default=None,
    help="Lighten (0 to 1) or darken (-1 to 0) the theme color. Default: 0.",
)
@click.option(
    "--label-color",
    default=None,
    help="Hex color for the data-label text.",
)
@click.option(
    "--label-background",
    default=None,
    help="Hex color for the data-label background. Default: match the "
    "measure's series color.",
)
@click.option(
    "--label-transparency",
    type=int,
    default=None,
    help="Data-label background transparency, 0-100. Default: 20, seeded "
    "only where a measure has none; set it to enforce it everywhere.",
)
@click.option(
    "--seed-label-transparency",
    "label_transparency_seed",
    type=int,
    default=None,
    help="Seed this data-label background transparency (0-100) where a "
    "measure has none, never overwriting an existing value.",
)
@click.option(
    "--show-labels/--hide-labels",
    "show_labels",
    default=None,
    help="Turn data labels on or off. Default: on for visuals without "
    "label settings; existing settings are kept unless this is set.",
)
@click.option(
    "--rebind-stale-line",
    "rebind_stale_line",
    is_flag=True,
    default=None,
    help="Before styling, point a line (Y2) measure projection whose name "
    "the model no longer declares at the current measure: leading symbols "
    "are stripped, then an exact name or a single case-insensitive match in "
    "the same table wins. The column role (Y) then counts as column side "
    "unless --exclude-role is given. Off by default.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Print a unified diff of what would change; write nothing. "
    "Exits 1 if any visual is out of style.",
)
@click.option(
    "--zip",
    "zip_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Also emit the styled report folder(s) as OUT.zip. Combine with "
    "--dry-run to produce the archive without touching the source files.",
)
def style(
    report_dir: Path,
    model_dir: Path | None,
    config_path: Path | None,
    tables: tuple[str, ...],
    renames: tuple[str, ...],
    exclude_roles: tuple[str, ...],
    visual_types: tuple[str, ...],
    line_color: str | None,
    palette: tuple[str, ...],
    color_pins: tuple[str, ...],
    theme_color_id: int | None,
    theme_color_percent: float | None,
    label_color: str | None,
    label_background: str | None,
    label_transparency: int | None,
    label_transparency_seed: int | None,
    show_labels: bool | None,
    rebind_stale_line: bool | None,
    dry_run: bool,
    zip_path: Path | None,
) -> None:
    """Style every combo chart in REPORT_DIR from its field parameters.

    REPORT_DIR is a PBIP *.Report folder, or any folder containing one or
    more of them (searched recursively), or a page folder or visual.json
    inside a report (only the visuals under it are restyled). Reads the measures declared in
    each report's semantic-model field-parameter tables and rebuilds each
    targeted visual's series colors, data labels, and label backgrounds,
    deterministically and idempotently, keeping every other formatting
    entry intact.
    """
    if config_path is None:
        default_config = Path.cwd() / DEFAULT_CONFIG_FILENAME
        if default_config.is_file():
            config_path = default_config

    table_renames: dict[str, str] = {}
    for entry in renames:
        name, sep, new_name = entry.partition("=")
        if not sep or not name.strip() or not new_name.strip():
            raise StylerError(
                f"--rename-table {entry!r} is not in OLD=NEW form. "
                f"For example: --rename-table \"y-Plot Specific=Set Lines\"."
            )
        table_renames[name.strip()] = new_name.strip()
    pins = _parse_pairs(
        color_pins, "--color", '"Sales Measures.Revenue=#7A4419"'
    )

    try:
        config = build_config(
            config_path,
            table_renames=table_renames or None,
            color_pins=pins or None,
            field_parameter_tables=tuple(tables) or None,
            visual_types=tuple(visual_types) or None,
            exclude_current_roles=tuple(exclude_roles) or None,
            line_color=line_color,
            palette=tuple(palette) or None,
            theme_color_id=theme_color_id,
            theme_color_percent=theme_color_percent,
            label_color=label_color,
            label_background=label_background,
            label_transparency=label_transparency,
            label_transparency_seed=label_transparency_seed,
            show_labels=show_labels,
            rebind_stale_line=rebind_stale_line,
        )
    except ConfigError as exc:
        raise StylerError(str(exc)) from exc

    within: Path | None = None
    if report_dir.is_file() or not is_report_dir(report_dir) and enclosing_report(report_dir):
        # a page folder or a visual file: restyle only what lies under it
        enclosing = enclosing_report(report_dir)
        if enclosing is None:
            raise StylerError(
                f"{report_dir} is not inside a *.Report folder. Pass a report "
                f"folder, a folder of reports, a page folder or a visual.json.")
        within, report_dir = report_dir.resolve(), enclosing
    discovery = _discover(report_dir)
    root = report_dir
    models: dict[Path, SemanticModel] = {}
    changes: list[VisualChange] = []
    all_keys: set[str] = set()
    # In a sweep of several reports with no --model, a report that cannot be
    # paired with a model (or whose model styles nothing) is skipped; a
    # single named report keeps the fatal error.
    lenient = not discovery.single and model_dir is None
    skipped_reports: list[tuple[Path, str]] = []

    def skip_or_fail(report: Path, reason: str) -> None:
        if not lenient:
            raise StylerError(reason)
        skipped_reports.append((report, reason))
        click.echo(f"Skipped:  {report.relative_to(root).as_posix()} ({reason})")

    for report in discovery.reports:
        if not discovery.single:
            click.echo(f"Report:   {report.relative_to(root).as_posix()}")
        try:
            resolved_model = (model_dir or resolve_model_dir(report)).resolve()
            if resolved_model not in models:
                models[resolved_model] = SemanticModel.load(resolved_model)
            model = models[resolved_model]
            tables = _expand_tables(config.field_parameter_tables, model)
            measure_keys = model.field_parameter_measures(tables) if tables else []
        except (FileNotFoundError, LookupError, OSError, ValueError) as exc:
            skip_or_fail(report, str(exc))
            continue

        if not measure_keys:
            skip_or_fail(report,
                f"no measures resolved from field-parameter tables "
                f"{list(config.field_parameter_tables)} in {resolved_model}, "
                f"so there is nothing to style. The tables exist, but none "
                f"of their NAMEOF references match a measure declared in the "
                f"model. Check that the configured tables reference "
                f"measures, not only columns."
            )
            continue
        all_keys.update(k.lower() for k in measure_keys)

        click.echo(f"Model:    {resolved_model}")
        click.echo(f"Measures: {len(measure_keys)} drive the styling")

        # every field parameter of the model can bind an excluded role
        # (v1.1.0 behaviour), not only the configured or matched tables
        catalogs = {
            table: [e.key for e in model.parameter_catalog(table)]
            for table in model.raw_by_table
        }
        try:
            changes.extend(
                plan_changes(
                    report,
                    measure_keys,
                    config,
                    catalogs={t: k for t, k in catalogs.items() if k},
                    slots=model.palette_slots(tables),
                    model=model,
                    within=within,
                )
            )
        except FileNotFoundError as exc:
            raise StylerError(str(exc)) from exc
        except RestyleInvariantError as exc:
            raise StylerError(
                f"refusing to write {report}: {exc}. This is a bug; please "
                f"report it with the visual.json involved."
            ) from exc

    unknown_pins = sorted(k for k, _ in config.colors if k.lower() not in all_keys)
    if unknown_pins:
        raise StylerError(
            f"color pin(s) {', '.join(repr(k) for k in unknown_pins)} match no "
            f"field-parameter measure. Use the \"Table.Measure\" key exactly "
            f"as the model declares it."
        )

    if not changes:
        raise StylerError(
            f"no targeted visuals found in {len(discovery.reports)} "
            f"report(s) under {root}: no visual has a visualType in "
            f"{list(config.visual_types)}. Check --visual-type or the "
            f"[targets] visual_types config key."
        )

    pending = [c for c in changes if c.changed]
    verb = "would rebind" if dry_run else "rebound"
    for change in changes:
        for rb in change.rebinds:
            click.echo(
                f"  {verb} {change.path.relative_to(root).as_posix()}: "
                f"{rb.entity}[{rb.old}] -> [{rb.new}]"
            )
    rebinds = sum(len(c.rebinds) for c in changes)
    totals = f"{rebinds} rebind(s), {len(skipped_reports)} skipped"
    if dry_run:
        for change in pending:
            click.echo()
            click.echo(change.unified_diff(root), nl=False)
        for change in pending:
            click.echo(_visual_detail(change, root, "would style"))
        click.echo(
            f"\n{len(pending)}/{len(changes)} visual(s) would change."
            if pending
            else f"\nAll {len(changes)} visual(s) already styled."
        )
        click.echo(f"Totals: {totals}.")
    else:
        written = apply_changes(changes)
        for change in pending:
            click.echo(_visual_detail(change, root, "styled"))
        click.echo(
            f"\nRestyled {written}/{len(changes)} visual(s); "
            f"{len(changes) - written} already styled."
        )
        click.echo(f"Totals: {totals}.")

    if zip_path is not None:
        write_zip(discovery.reports, changes, zip_path, base=root.parent)
        click.echo(f"Wrote {zip_path}")

    if dry_run and pending:
        sys.exit(EXIT_DRIFT)


def _expand_tables(names: tuple[str, ...], model: SemanticModel) -> tuple[str, ...]:
    """Field-parameter table names with each shell-style pattern expanded.

    A pattern matches the model's tables case-insensitively (in name order);
    one that matches nothing adds nothing. Plain names are kept as given.
    """
    import fnmatch

    out: list[str] = []
    for name in names:
        if any(ch in name for ch in "*?["):
            matched = sorted(t for t in model.raw_by_table
                             if fnmatch.fnmatchcase(t.lower(), name.lower()))
        else:
            matched = [name]
        out += [t for t in matched if t not in out]
    return tuple(out)


def _visual_detail(change: VisualChange, root: Path, verb: str) -> str:
    counts = ", ".join(f"{card} {before} -> {after}" for card, before, after in change.counts)
    line = f"  {verb} {change.path.relative_to(root).as_posix()}: {counts}"
    if change.excluded:
        line += f"; column side, not styled: {', '.join(change.excluded)}"
    return line


# -- check ---------------------------------------------------------------------
def _rule_help() -> str:
    return ", ".join(rules())


def _filtered_reports(path: Path, report_name: str | None, model_name: str | None,
                      settings: Settings):
    """Discover reports, then apply --report / --model-name / exclusions."""
    discovery = discover_reports(path)
    reports = list(discovery.reports)
    filters = []
    if report_name:
        wanted = {report_name, f"{report_name}.Report"}
        reports = [r for r in reports if r.name in wanted]
        filters.append(f"--report {report_name!r}")
    else:
        if model_name:
            reports = [r for r in reports if report_model_name(r) == model_name]
            filters.append(f"--model-name {model_name!r}")
        if not discovery.single:
            excluded = set(settings.canvas.exclude_reports)
            reports = [r for r in reports if r.name not in excluded]
    return discovery, reports, filters


@main.command("check")
@click.argument(
    "path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)
@click.option(
    "--model",
    "model_dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help="Semantic-model folder, used for every report found. Default: "
    "resolved per report from its definition.pbir.",
)
@click.option(
    "--rule",
    "rule_slugs",
    multiple=True,
    metavar="SLUG",
    help="Run this rule instead of the default 'integrity' checks "
    "(repeatable). Rules: integrity, slicer-gates, slicer-mode-gates, "
    "category-filter, theme, visual-position, y-combo, filter-panel, "
    "format-selector, stale-placeholders, answer-bookmarks, bookmark-literals.",
)
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=False, dir_okay=False, path_type=Path),
    default=None,
    help=f"Config file (TOML) with the canvas sections. Default: "
    f"./{DEFAULT_CONFIG_FILENAME} if present.",
)
@click.option(
    "--report",
    "report_name",
    default=None,
    help="Check only the report folder with this name (with or without the "
    ".Report suffix). Overrides the excluded-reports list.",
)
@click.option(
    "--model-name",
    "model_name",
    default=None,
    help="Check only reports whose definition.pbir points at "
    "<NAME>.SemanticModel.",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Print the result as JSON instead of text.",
)
@click.option(
    "--fix",
    is_flag=True,
    help="Run the fixers of the selected rules (integrity: BMK001, BMK002), "
    "then check again. Fixers write only the files that need a change.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="With --fix: print the diff of every change the fixers would make "
    "and write nothing. Exits 1 when there is something to fix.",
)
@click.option(
    "--summary",
    is_flag=True,
    help="Report compliance with the four foundation rules (slicer-gates, "
    "category-filter, theme, filter-panel). Never fails.",
)
@click.option(
    "--only-display-names",
    "only_names",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="bookmark-literals: check only the bookmarks whose display names "
    "are listed in this JSON file (a list of strings).",
)
@click.option(
    "--baseline",
    "baseline_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Accepted-findings file. Only findings not in it fail the run.",
)
@click.option(
    "--update-baseline",
    is_flag=True,
    help="Write every current finding to the --baseline file and exit 0.",
)
def check(
    path: Path,
    model_dir: Path | None,
    rule_slugs: tuple[str, ...],
    config_path: Path | None,
    report_name: str | None,
    model_name: str | None,
    as_json: bool,
    fix: bool,
    dry_run: bool,
    summary: bool,
    only_names: Path | None,
    baseline_path: Path | None,
    update_baseline: bool,
) -> None:
    """Check the PBIP report(s) under PATH.

    Without --rule, runs the integrity checks: field bindings resolve in the
    paired model, bookmarks are importable and point at real pages and
    visuals, field-parameter slots are consistent, theme files exist. With
    --rule SLUG, runs that convention rule instead. Read-only unless --fix
    is given. Exits 0 when there are no new errors, 1 when there are, 2 on
    a setup problem.
    """
    registry = rules()
    slugs = list(SUMMARY_RULES) if summary else list(dict.fromkeys(rule_slugs or ("integrity",)))
    unknown = [s for s in slugs if s not in registry]
    if unknown:
        raise StylerError(
            f"unknown rule(s) {', '.join(unknown)}. Valid rules: {_rule_help()}."
        )
    if dry_run and not fix:
        raise StylerError("--dry-run only applies to --fix: add --fix to preview the fixes.")
    if config_path is None:
        default_config = Path.cwd() / DEFAULT_CONFIG_FILENAME
        if default_config.is_file():
            config_path = default_config
    elif not config_path.is_file():
        raise StylerError(f"config file {config_path} does not exist. Check the --config path.")
    try:
        settings = load_settings(config_path)
    except SettingsError as exc:
        raise StylerError(str(exc)) from exc
    configured_baseline = settings.answer_bookmarks.baseline
    if baseline_path is None and configured_baseline and "answer-bookmarks" in slugs:
        # [answer_bookmarks] baseline, relative to the config file
        baseline_path = (config_path.parent if config_path else Path.cwd()) / configured_baseline
    if update_baseline and baseline_path is None:
        raise StylerError("--update-baseline needs --baseline FILE to write to.")
    accepted: set[tuple[str, str]] = set()
    if baseline_path is not None and not update_baseline:
        if not baseline_path.is_file():
            raise StylerError(
                f"baseline file {baseline_path} does not exist. Create it "
                f"with --baseline {baseline_path} --update-baseline."
            )
        try:
            accepted = load_baseline(baseline_path)
        except (ValueError, json.JSONDecodeError) as exc:
            raise StylerError(str(exc)) from exc
    # a guard finding means nothing was checked: no baseline may accept it
    accepted = {k for k in accepted if k[0] not in UNBASELINABLE}

    options: dict = {}
    if only_names is not None:
        try:
            options["only_display_names"] = load_display_name_filter(only_names)
        except (ValueError, json.JSONDecodeError) as exc:
            raise StylerError(str(exc)) from exc

    discovery, reports, filters = _filtered_reports(path, report_name, model_name, settings)
    for skipped, reason in discovery.skipped:
        if not as_json:
            click.echo(f"Skipped:  {skipped.relative_to(path).as_posix()} ({reason})", err=True)
    if not reports:
        named = f" matching {' and '.join(filters)}" if filters else ""
        raise StylerError(
            f"nothing matched: no *.Report folders{named} under {path}. Pass a "
            f"PBIP report folder (one containing definition.pbir and "
            f"definition/pages), or a folder that contains one or more of them."
        )
    root = path if not discovery.single else path.parent
    report_labels = {r: r.relative_to(root).as_posix() for r in reports}
    contexts, notes, model_findings = _load_models(reports, root, model_dir, settings, options)
    fixed: list[tuple[Path, str]] = []
    planned: list[tuple[Path, str]] = []
    diffs: list[str] = []
    refused: list[tuple[Path, str]] = []
    findings: list[Finding] = []
    skipped_notes: list[str] = []
    checked: dict[str, int] = {}
    details: dict[str, dict[str, int]] = {}

    def keep_notes(ctx: RuleContext) -> None:
        skipped_notes.extend(n for n in ctx.skipped if n not in skipped_notes)

    if fix:
        fixers = [registry[s] for s in slugs if registry[s].fix is not None]
        # Everything a fixer needs is checked for every report before any
        # report is written, so a setup problem never leaves half a fix.
        try:
            for report in reports:
                for rule in fixers:
                    if rule.prepare is not None:
                        rule.prepare(contexts[report]())
        except RuleError as exc:
            raise StylerError(f"{exc}. --fix stopped before writing: nothing was written.") from exc
        if dry_run:
            planned, diffs, refused = _plan_fixes(reports, root, fixers, contexts, keep_notes)
        else:
            try:
                for report in reports:
                    for rule in fixers:
                        ctx = contexts[report]()
                        fixed += rule.fix(ctx)
                        refused += ctx.options.pop("refused", [])
                        keep_notes(ctx)
            except RuleError as exc:
                raise StylerError(_partial_fix_message(exc, fixed, root)) from exc

    for report in reports:
        ctx = contexts[report]()
        try:
            for slug in slugs:
                registry[slug].check(ctx)
        except RuleError as exc:
            raise StylerError(str(exc)) from exc
        findings += sorted(model_findings.get(report, []) + ctx.findings,
                           key=lambda f: (f.file, f.check_id, f.subject))
        keep_notes(ctx)
        for slug, n in ctx.checked.items():
            checked[slug] = checked.get(slug, 0) + n
        for slug, counts in ctx.details.items():
            total = details.setdefault(slug, {})
            for what, n in counts.items():
                total[what] = total.get(what, 0) + n

    if "bookmark-literals" in slugs and "bookmark-literals" not in checked:
        raise StylerError(
            "bookmark-literals judged no report: it needs the paired semantic model "
            "(definition.pbir next to a local *.SemanticModel); pass --model "
            "<*.SemanticModel folder>")
    current = {f.key for f in findings}
    new = [f for f in findings if f.key not in accepted]
    in_scope = _baseline_scope(registry, slugs, report_labels.values())
    healed = sorted(k for k in accepted - current if in_scope(k))
    guards = [f for f in findings if f.check_id in UNBASELINABLE]
    if update_baseline:
        kept = []
        if baseline_path.is_file():
            try:
                kept = [k for k in load_baseline(baseline_path)
                        if not in_scope(k) and k[0] not in UNBASELINABLE]
            except (ValueError, json.JSONDecodeError) as exc:
                raise StylerError(str(exc)) from exc
        write_baseline(baseline_path, [f for f in findings if f.check_id not in UNBASELINABLE],
                       keep=kept)
    new_errors = [f for f in new if f.severity == "error"]
    failing = (bool(new_errors) and not update_baseline or bool(guards)) and not summary
    exit_code = EXIT_DRIFT if failing or (dry_run and planned) else EXIT_OK
    compliance = _compliance(registry, findings, checked) if summary else None

    if as_json:
        payload = {
            "tool": "pbi-plot-styler",
            "version": __version__,
            "rules": slugs,
            "reports": [r.relative_to(root).as_posix() for r in reports],
            "findings": [
                {**f.to_dict(), "baselined": f.key in accepted,
                 **({"fix": fix_hint(f.check_id)} if summary else {})}
                for f in findings
            ],
            "checked": details,
            "healed": [{"id": i, "location": loc} for i, loc in healed],
            "fixed": [
                {"file": p.relative_to(root).as_posix(), "change": d} for p, d in fixed
            ],
            "planned": [
                {"file": p.relative_to(root).as_posix(), "change": d} for p, d in planned
            ],
            "refused": [
                {"file": p.relative_to(root).as_posix(), "reason": r} for p, r in refused
            ],
            "skipped": skipped_notes,
            "notes": notes,
            "summary": {
                "errors": sum(f.severity == "error" for f in findings),
                "warnings": sum(f.severity == "warning" for f in findings),
                "new": len(new),
                "baselined": len(findings) - len(new),
                "healed": len(healed),
            },
            "exit_code": exit_code,
        }
        if compliance is not None:
            payload["compliance"] = compliance
        click.echo(json.dumps(payload, indent=2))
    else:
        for note in notes:
            click.echo(f"note: {note}", err=True)
        for note in skipped_notes:
            click.echo(f"skipped  {note}")
        for p, d in fixed:
            click.echo(f"fixed    {p.relative_to(root).as_posix()}: {d}")
        for p, d in planned:
            click.echo(f"would fix {p.relative_to(root).as_posix()}: {d}")
        for diff in diffs:
            click.echo(diff, nl=False)
        for p, r in refused:
            click.echo(f"REFUSED  {p.relative_to(root).as_posix()}: {r}")
        for f in new:
            click.echo(f"{f.severity.upper():<8} {f.check_id}  {f.file}: {f.message}")
        for check_id, location in healed:
            click.echo(f"healed   {check_id}  {location}")
        if healed:
            click.echo("hint: run with --update-baseline to lock the improvement in.")
        for slug, counts in details.items():
            click.echo(f"checked  {slug}: " + ", ".join(f"{n} {what}" for what, n in counts.items()))
        if compliance is not None:
            click.echo(_compliance_text(compliance, findings))
        errors = sum(f.severity == "error" for f in new)
        warnings = len(new) - errors
        text = (
            f"\nChecked {len(reports)} report(s): {errors} error(s), "
            f"{warnings} warning(s)"
        )
        if accepted:
            text += (
                f", {len(findings) - len(new)} accepted by the baseline, "
                f"{len(healed)} healed"
            )
        click.echo(text + ".")
        if update_baseline:
            written = len(current) - len({f.key for f in guards})
            click.echo(f"Wrote {written} finding(s) to {baseline_path}.")
            if guards:
                click.echo(f"{guards[0].check_id} is never written to a baseline: "
                           f"{guards[0].message}")

    sys.exit(exit_code)


def _load_models(reports, root: Path, model_dir: Path | None, settings: Settings,
                 options: dict):
    """One context factory per report, the notes, and MDL001 per report.

    A report with no local model reference is only a note. A model that is
    referenced but cannot be loaded is an ``MDL001`` error: the rules that
    need it are skipped, and their notes say why.
    """
    loaded: dict[Path, SemanticModel | Exception] = {}
    contexts = {}
    notes: list[str] = []
    model_findings: dict[Path, list[Finding]] = {}
    for report in reports:
        label = report.relative_to(root).as_posix()
        model: SemanticModel | None = None
        error: str | None = None
        try:
            resolved = (model_dir or resolve_model_dir(report)).resolve()
        except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
            notes.append(f"{label}: binding checks skipped, no local semantic model ({exc})")
            resolved = None
        if resolved is not None and not resolved.is_dir():
            notes.append(f"{label}: binding checks skipped, no local semantic model "
                         f"({resolved.name} is not a folder next to the report)")
            resolved = None
        if resolved is not None:
            if resolved not in loaded:
                try:
                    loaded[resolved] = SemanticModel.load(resolved)
                except (OSError, ValueError, json.JSONDecodeError) as exc:
                    loaded[resolved] = exc
            outcome = loaded[resolved]
            if isinstance(outcome, Exception):
                error = str(outcome) or type(outcome).__name__
                source = report / "definition.pbir" if model_dir is None else resolved
                where = (source.relative_to(root).as_posix()
                         if source.is_relative_to(root) else source.as_posix())
                model_findings[report] = [Finding(
                    "MDL001", where, resolved.name,
                    f"the semantic model {resolved.name} cannot be loaded: {error}")]
            else:
                model = outcome

        def factory(report=report, model=model, error=error) -> RuleContext:
            return RuleContext(report, root, model, settings=settings, options=options,
                               model_error=error)
        contexts[report] = factory
    return contexts, notes, model_findings


def _plan_fixes(reports, root: Path, fixers, contexts, keep_notes):
    """Run the fixers on a scratch copy of each report: what would change.

    Returns ``(planned, diffs, refused)``; nothing under ``root`` is written.
    """
    import difflib
    import shutil
    import tempfile

    planned: list[tuple[Path, str]] = []
    diffs: list[str] = []
    refused: list[tuple[Path, str]] = []
    with tempfile.TemporaryDirectory() as scratch:
        for report in reports:
            rel = report.relative_to(root)
            copy = Path(scratch) / rel
            shutil.copytree(report, copy)
            before = {p.relative_to(copy): p.read_bytes() for p in copy.rglob("*") if p.is_file()}
            real = contexts[report]()
            for rule in fixers:
                ctx = RuleContext(copy, Path(scratch), real.model, settings=real.settings,
                                  options=real.options, model_error=real.model_error)
                try:
                    changes = rule.fix(ctx)
                except RuleError as exc:
                    raise StylerError(f"{exc}. Dry run: nothing was written.") from exc
                planned += [(root / p.relative_to(scratch), d) for p, d in changes]
                refused += [(root / p.relative_to(scratch), r)
                            for p, r in ctx.options.pop("refused", [])]
                keep_notes(ctx)
            after = {p.relative_to(copy): p.read_bytes() for p in copy.rglob("*") if p.is_file()}
            for name in sorted(set(before) | set(after)):
                old, new = before.get(name, b""), after.get(name, b"")
                if old == new:
                    continue
                shown = (rel / name).as_posix()
                diffs.append("".join(difflib.unified_diff(
                    old.decode("utf-8-sig").splitlines(keepends=True),
                    new.decode("utf-8-sig").splitlines(keepends=True),
                    fromfile=f"a/{shown}" if name in before else "/dev/null",
                    tofile=f"b/{shown}" if name in after else "/dev/null")))
    return planned, diffs, refused


def _partial_fix_message(exc: Exception, fixed, root: Path) -> str:
    """The error for a fixer that failed after others had written."""
    if not fixed:
        return f"{exc}. --fix stopped: nothing was written."
    lines = [f"{exc}. --fix stopped; these changes were already written:"]
    lines += [f"  {p.relative_to(root).as_posix()}: {d}" for p, d in fixed]
    return "\n".join(lines)


def _baseline_scope(registry, slugs, report_labels):
    """Whether a baseline entry belongs to this run (and is rewritten by it)."""
    ids = {"MDL001"}
    for slug in slugs:
        ids.update(registry[slug].ids)
    prefixes = tuple(f"{label}/" for label in report_labels)

    def in_scope(entry: tuple[str, str]) -> bool:
        check_id, location = entry
        return check_id in ids and location.startswith(prefixes)
    return in_scope


def _compliance(registry, findings: list[Finding], checked: dict[str, int]) -> dict:
    """Per-rule compliance for the foundation rules (``--summary``)."""
    rows = []
    for slug in SUMMARY_RULES:
        rule = registry[slug]
        own = [f for f in findings if f.check_id in rule.summarised]
        critical = [f for f in own if f.check_id in rule.critical and f.severity == "error"]
        total = checked.get(slug, 0)
        failing = len({f.location for f in critical})
        rows.append({
            "rule": slug,
            "title": rule.title,
            "checked": total,
            "passed": max(total - failing, 0),
            # any error finding of the rule breaks compliance, not only the
            # critical ids (those still decide the passed count)
            "compliant": not any(f.severity == "error" for f in own),
            "errors": sum(f.severity == "error" for f in own),
            "warnings": sum(f.severity == "warning" for f in own),
        })
    compliant = sum(r["compliant"] for r in rows)
    return {
        "total_rules": len(rows),
        "compliant_rules": compliant,
        "compliance_percentage": round(100.0 * compliant / len(rows), 1),
        "errors": sum(r["errors"] for r in rows),
        "warnings": sum(r["warnings"] for r in rows),
        "overall_compliance": compliant == len(rows)
        and not any(r["errors"] for r in rows),
        "rules": rows,
    }


def _compliance_text(compliance: dict, findings: list[Finding]) -> str:
    lines = ["", "## Foundation rules", ""]
    registry = rules()
    for row in compliance["rules"]:
        status = "PASS" if row["compliant"] else "FAIL"
        lines.append(f"- **{status}** `{row['rule']}`: {row['title']} "
                     f"({row['passed']}/{row['checked']} passed)")
        for f in findings:
            if f.check_id in registry[row["rule"]].summarised:
                lines.append(f"  - {f.severity} {f.check_id} {f.subject}: {f.message}")
                lines.append(f"    fix: {fix_hint(f.check_id)}")
    lines.append("")
    lines.append(
        f"Compliance: {compliance['compliant_rules']}/{compliance['total_rules']} "
        f"rules ({compliance['compliance_percentage']}%), "
        f"{compliance['errors']} error(s), {compliance['warnings']} warning(s)."
    )
    return "\n".join(lines)


# -- colors ----------------------------------------------------------------------
#: ``colors`` exit codes: 0 done or nothing to do, 1 a dry run found changes,
#: 2 usage error (bad option, unreadable model, unparsable palette).
EXIT_COLORS_PENDING = 1
EXIT_INVALID = 2


@main.group("colors")
def colors() -> None:
    """Stamp each measure's palette colour from the model's palette measure."""


def _color_options(func):
    func = click.option("--report", "report_dir", required=True,
                        type=click.Path(exists=True, file_okay=False, path_type=Path),
                        help="The *.Report folder.")(func)
    func = click.option("--model", "model_dir", default=None,
                        type=click.Path(exists=True, file_okay=False, path_type=Path),
                        help="The *.SemanticModel folder. Default: from definition.pbir.")(func)
    func = click.option("--apply", is_flag=True,
                        help="Write the changes. Without it nothing is written.")(func)
    func = click.option("--measure", default="c-Measure Color", show_default=True,
                        help="The palette measure.")(func)
    func = click.option("--palette-table", default="w-Colors", show_default=True,
                        help="The table searched first for the palette measure.")(func)
    func = click.option("--default-color-id", type=int, default=9, show_default=True,
                        help="Theme data colour that reset reverts chart fills to.")(func)
    return func


def _run_colors(action, report_dir: Path, model_dir: Path | None, apply: bool,
                opts: ColorOptions) -> None:
    try:
        model = model_dir or resolve_model_dir(report_dir)
        result = action(report_dir, model, opts, apply)
    except (PaletteError, FileNotFoundError, json.JSONDecodeError) as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(EXIT_INVALID)
    for line in result.info:
        click.echo(line)
    for note in result.notes:
        click.echo(f"note: {note}")
    for change in result.changes:
        click.echo(f"  {change}")
    if action is color_sync:
        click.echo(f"{result.rewritten} entr{'y' if result.rewritten == 1 else 'ies'} "
                   f"rewritten, {result.added} added.")
    if apply:
        click.echo(f"APPLIED: {len(result.written)} file(s) written.")
    else:
        click.echo(f"DRY RUN: {len(result.changes)} change(s); rerun with --apply to write.")
    pending = bool(result.changes) and not apply
    sys.exit(EXIT_COLORS_PENDING if pending else EXIT_OK)


@colors.command("sync")
@_color_options
@click.option("--visual-type", "visual_types", multiple=True,
              help="Visual type to stamp (repeatable). Default: bar, line, combo "
              "charts and matrices.")
@click.option("--min-series", type=int, default=2, show_default=True,
              help="A bookmark capture with this many Y measures is multi-series.")
@click.option("--all-visuals", is_flag=True,
              help="Stamp every supported visual, not only the ones in scope.")
def colors_sync(report_dir, model_dir, apply, measure, palette_table, default_color_id,
                visual_types, min_series, all_visuals) -> None:
    """Colour each measure from its palette slot (dry run unless --apply).

    Exits 0 when the changes were written or none are needed, 1 when a dry
    run found changes to make, 2 on invalid input.
    """
    opts = ColorOptions(measure=measure, host_table=palette_table,
                        default_color_id=default_color_id,
                        visual_types=tuple(visual_types) or ColorOptions().visual_types,
                        min_series=min_series, all_visuals=all_visuals)
    _run_colors(color_sync, report_dir, model_dir, apply, opts)


@colors.command("reset")
@_color_options
@click.option("--visual-type", "visual_types", multiple=True,
              help="Visual type to revert (repeatable), on visuals and bookmark "
              "captures. Default: bar, line, combo charts and matrices.")
def colors_reset(report_dir, model_dir, apply, measure, palette_table,
                 default_color_id, visual_types) -> None:
    """Revert palette colours written by sync (dry run unless --apply).

    Only the picker's registered measures are reverted, on visuals and on
    bookmark overrides.
    """
    opts = ColorOptions(measure=measure, host_table=palette_table,
                        default_color_id=default_color_id,
                        visual_types=tuple(visual_types) or ColorOptions().visual_types)
    _run_colors(color_reset, report_dir, model_dir, apply, opts)


# -- rename-label ----------------------------------------------------------------
@main.command("rename-label")
@click.argument("client_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--pair", "pairs", nargs=2, multiple=True, required=True,
              metavar="OLD NEW", help="Old and new row label (repeatable).")
@click.option("--table-pattern", "patterns", multiple=True,
              help="Selector tables to edit (glob, repeatable). Default: x-*.")
@click.option("--apply", is_flag=True, help="Write the changes.")
def rename_label(client_dir: Path, pairs, patterns, apply: bool) -> None:
    """Rename a field-parameter row label in the model and every report.

    Edits the selector tables of every *.SemanticModel directly under
    CLIENT_DIR and the visuals, pages and bookmarks of every *.Report below
    it. Only the quoted label ("OLD") is replaced. Dry run unless --apply.
    """
    try:
        result = rename_labels(client_dir, [tuple(p) for p in pairs], apply=apply,
                               patterns=tuple(patterns) or ("x-*",))
    except LabelRenameError as exc:
        raise StylerError(str(exc)) from exc
    for old, new, count in result.counts:
        click.echo(f'"{old}" -> "{new}": {count} occurrence(s)')
    verb = "APPLIED" if apply else "DRY RUN"
    click.echo(f"{verb}: {len(result.touched)} file(s)")
    for path in result.touched:
        click.echo(f"  {path.relative_to(client_dir).as_posix()}")


# -- rename-measure ----------------------------------------------------------------
@main.command("rename-measure")
@click.argument("old")
@click.argument("new")
@click.option("--model", "model_dir", required=True,
              type=click.Path(exists=True, file_okay=False, path_type=Path),
              help="The *.SemanticModel folder; every *.Report below its parent "
              "folder (at any depth) is a report root.")
@click.option("--label-from", default=None, help="Old label (default: OLD).")
@click.option("--label-to", default=None, help="New label (default: NEW).")
@click.option("--dry-run", is_flag=True, help="Count the references; write nothing.")
def rename_measure_cmd(old: str, new: str, model_dir: Path, label_from, label_to,
                       dry_run: bool) -> None:
    """Rename measure OLD to NEW in every visual and bookmark of the reports.

    The model side (the measure declaration and DAX) is not edited. The
    dry-run count equals the number of rewrites a real run makes.
    """
    roots = report_roots(model_dir)
    if dry_run:
        total = count_measure_refs(roots, old, label_from)
        click.echo(f"DRY RUN: {total} reference(s) to [{old}] in {len(roots)} report(s).")
        return

    def report_file(path: Path, hits: int) -> None:
        click.echo(f"  {path.relative_to(model_dir.parent).as_posix()}: {hits}")

    total = rename_measure(roots, old, new, label_from, label_to, on_file=report_file)
    click.echo(f"APPLIED: {total} reference(s) renamed to [{new}] in {len(roots)} report(s).")


# -- bookmarks build --------------------------------------------------------------
@main.group("bookmarks")
def bookmarks() -> None:
    """Build answer bookmarks from a working base bookmark."""


@bookmarks.command("build")
@click.argument("entries", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--report", "report_dir", required=True,
              type=click.Path(exists=True, file_okay=False, path_type=Path),
              help="The *.Report folder.")
@click.option("--config", "config_path", default=None,
              type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help=f"Config file with a [bookmarks] section. Default: "
              f"./{DEFAULT_CONFIG_FILENAME} if present.")
@click.option("--base", default=None, help="Base bookmark name (overrides [bookmarks] base).")
@click.option("--group", default=None,
              help="bookmarks.json group to register new bookmarks in.")
@click.option("--keep-ids", is_flag=True,
              help="Re-render: an existing bookmark with the entry's display name "
              "is the base and keeps its name; new ones go first in the group.")
@click.option("--legacy-layout", is_flag=True,
              help="Single-page layout: the measures picker fills the matrix "
              "values (3 or more) and unused pickers are emptied.")
@click.option("--dry-run", is_flag=True, help="Build everything, write nothing.")
def bookmarks_build(entries: Path, report_dir: Path, config_path: Path | None,
                    base: str | None, group: str | None, keep_ids: bool,
                    legacy_layout: bool, dry_run: bool) -> None:
    """Render one bookmark per entry of ENTRIES (a JSON list) into the report."""
    if config_path is None and (Path.cwd() / DEFAULT_CONFIG_FILENAME).is_file():
        config_path = Path.cwd() / DEFAULT_CONFIG_FILENAME
    try:
        settings = load_builder_settings(config_path)
        result = build_bookmarks(report_dir, entries, settings, base=base, group=group,
                                 keep_ids=keep_ids, legacy=legacy_layout, dry_run=dry_run)
    except BuildError as exc:
        raise StylerError(str(exc)) from exc
    verb = "would write" if dry_run else "wrote"
    for note in result.notes:
        click.echo(f"  note: {note}")
    for path, display, kept in result.details:
        origin = "kept id" if kept else "new id"
        click.echo(f"  {verb} {path.relative_to(report_dir).as_posix()} ({origin}): {display}")
    for group_name, names in result.registered.items():
        where = "at the top level" if group_name == TOP_LEVEL else f"in group {group_name}"
        click.echo(f"  registered {len(names)} bookmark(s) {where}")
    click.echo(f"{len(result.written)} bookmark(s) {'built (dry run)' if dry_run else 'built'}.")


__all__ = ["main", "style", "check", "colors", "bookmarks", "CHECKS"]

if __name__ == "__main__":  # pragma: no cover
    main()

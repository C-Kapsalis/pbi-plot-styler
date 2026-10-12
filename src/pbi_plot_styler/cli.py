"""Command-line interface for pbi-plot-styler.

Two commands: ``style`` (the default, so ``pbi-plot-styler REPORT_DIR``
keeps working exactly as before) and ``check`` (read-only integrity checks).

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
    check_report,
    fix_report,
    load_baseline,
    write_baseline,
)
from .config import DEFAULT_CONFIG_FILENAME, ConfigError, build_config
from .report import (
    RestyleInvariantError,
    VisualChange,
    apply_changes,
    discover_reports,
    plan_changes,
    resolve_model_dir,
    write_zip,
)
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

    This keeps the original ``pbi-plot-styler REPORT_DIR [OPTIONS]`` form
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
    """Style Power BI combo charts from their field parameters, and check
    PBIP reports for broken bindings and bookmarks.

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
    type=click.Path(exists=True, file_okay=False, path_type=Path),
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
    help="Field-parameter table name (repeatable). Overrides the default "
    "'x-Plot Specific 1' / 'x-Plot Specific 2' / 'y-Plot Specific' trio.",
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
    "--show-labels/--hide-labels",
    "show_labels",
    default=None,
    help="Turn data labels on or off. Default: on for visuals without "
    "label settings; existing settings are kept unless this is set.",
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
    show_labels: bool | None,
    dry_run: bool,
    zip_path: Path | None,
) -> None:
    """Style every combo chart in REPORT_DIR from its field parameters.

    REPORT_DIR is a PBIP *.Report folder, or any folder containing one or
    more of them (searched recursively). Reads the measures declared in
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
            show_labels=show_labels,
        )
    except ConfigError as exc:
        raise StylerError(str(exc)) from exc

    discovery = _discover(report_dir)
    root = report_dir
    models: dict[Path, SemanticModel] = {}
    changes: list[VisualChange] = []
    all_keys: set[str] = set()

    for report in discovery.reports:
        if not discovery.single:
            click.echo(f"Report:   {report.relative_to(root).as_posix()}")
        try:
            resolved_model = (model_dir or resolve_model_dir(report)).resolve()
            if resolved_model not in models:
                models[resolved_model] = SemanticModel.load(resolved_model)
            model = models[resolved_model]
            measure_keys = model.field_parameter_measures(
                config.field_parameter_tables
            )
        except (FileNotFoundError, LookupError) as exc:
            raise StylerError(str(exc)) from exc

        if not measure_keys:
            raise StylerError(
                f"no measures resolved from field-parameter tables "
                f"{list(config.field_parameter_tables)} in {resolved_model}, "
                f"so there is nothing to style. The tables exist, but none "
                f"of their NAMEOF references match a measure declared in the "
                f"model. Check that the configured tables reference "
                f"measures, not only columns."
            )
        all_keys.update(k.lower() for k in measure_keys)

        click.echo(f"Model:    {resolved_model}")
        click.echo(f"Measures: {len(measure_keys)} drive the styling")

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
                    slots=model.palette_slots(config.field_parameter_tables),
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
    if dry_run:
        for change in pending:
            click.echo()
            click.echo(change.unified_diff(root), nl=False)
        click.echo(
            f"\n{len(pending)}/{len(changes)} visual(s) would change."
            if pending
            else f"\nAll {len(changes)} visual(s) already styled."
        )
    else:
        written = apply_changes(changes)
        for change in pending:
            click.echo(f"  styled {change.path.relative_to(root).as_posix()}")
        click.echo(
            f"\nRestyled {written}/{len(changes)} visual(s); "
            f"{len(changes) - written} already styled."
        )

    if zip_path is not None:
        write_zip(discovery.reports, changes, zip_path, base=root.parent)
        click.echo(f"Wrote {zip_path}")

    if dry_run and pending:
        sys.exit(EXIT_DRIFT)


# -- check ---------------------------------------------------------------------
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
    "--json",
    "as_json",
    is_flag=True,
    help="Print the result as JSON instead of text.",
)
@click.option(
    "--fix",
    is_flag=True,
    help="Repair the fixable findings (BMK001, BMK002) in place with "
    "surgical, verified text edits, then check again.",
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
    as_json: bool,
    fix: bool,
    baseline_path: Path | None,
    update_baseline: bool,
) -> None:
    """Check the PBIP report(s) under PATH for integrity problems.

    Read-only unless --fix is given. Checks that field bindings resolve in
    the paired model, that bookmarks are importable and point at real
    pages and visuals, that field-parameter slots are consistent, and that
    the theme files exist. Exits 0 when there are no new errors, 1 when
    there are, 2 on a setup problem.
    """
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

    discovery = _discover(path)
    root = path if not discovery.single else path.parent
    models: dict[Path, SemanticModel] = {}
    notes: list[str] = []
    fixed: list[tuple[Path, str]] = []
    refused: list[tuple[Path, str]] = []
    findings: list[Finding] = []

    for report in discovery.reports:
        model: SemanticModel | None = None
        try:
            resolved = (model_dir or resolve_model_dir(report)).resolve()
            if resolved not in models:
                models[resolved] = SemanticModel.load(resolved)
            model = models[resolved]
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            notes.append(
                f"{report.relative_to(root).as_posix()}: binding checks "
                f"skipped, no local semantic model ({exc})"
            )
        if fix:
            done, bad = fix_report(report)
            fixed += done
            refused += bad
        findings += check_report(report, root, model)

    current = {f.key for f in findings}
    new = [f for f in findings if f.key not in accepted]
    healed = sorted(accepted - current)
    if update_baseline:
        write_baseline(baseline_path, findings)
    new_errors = [f for f in new if f.severity == "error"]
    exit_code = EXIT_OK if update_baseline or not new_errors else EXIT_DRIFT

    if as_json:
        payload = {
            "tool": "pbi-plot-styler",
            "version": __version__,
            "reports": [r.relative_to(root).as_posix() for r in discovery.reports],
            "findings": [
                {**f.to_dict(), "baselined": f.key in accepted} for f in findings
            ],
            "healed": [{"id": i, "location": loc} for i, loc in healed],
            "fixed": [
                {"file": p.relative_to(root).as_posix(), "change": d} for p, d in fixed
            ],
            "refused": [
                {"file": p.relative_to(root).as_posix(), "reason": r} for p, r in refused
            ],
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
        click.echo(json.dumps(payload, indent=2))
    else:
        for note in notes:
            click.echo(f"note: {note}", err=True)
        for p, d in fixed:
            click.echo(f"fixed    {p.relative_to(root).as_posix()}: {d}")
        for p, r in refused:
            click.echo(f"REFUSED  {p.relative_to(root).as_posix()}: {r}")
        for f in new:
            click.echo(f"{f.severity.upper():<8} {f.check_id}  {f.file}: {f.message}")
        for check_id, location in healed:
            click.echo(f"healed   {check_id}  {location}")
        errors = sum(f.severity == "error" for f in new)
        warnings = len(new) - errors
        summary = (
            f"\nChecked {len(discovery.reports)} report(s): {errors} error(s), "
            f"{warnings} warning(s)"
        )
        if accepted:
            summary += (
                f", {len(findings) - len(new)} accepted by the baseline, "
                f"{len(healed)} healed"
            )
        click.echo(summary + ".")
        if update_baseline:
            click.echo(f"Wrote {len(current)} finding(s) to {baseline_path}.")

    sys.exit(exit_code)


__all__ = ["main", "style", "check", "CHECKS"]

if __name__ == "__main__":  # pragma: no cover
    main()

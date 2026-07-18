"""Command-line interface for pbi-plot-styler.

Style notes (deliberate deviations from the Heroku CLI style guide):
help descriptions are complete sentences with sentence-case capitalization
and terminal periods, following the Click ecosystem convention rather than
Heroku's lowercase-no-period rule. Errors go to stderr and exit codes are
CI-grade (0 ok / 1 drift / 2 error), which the guide and the docs agree on.
"""
from __future__ import annotations

import sys
from pathlib import Path

import click

from . import __version__
from .config import DEFAULT_CONFIG_FILENAME, ConfigError, build_config
from .report import (
    apply_changes,
    plan_changes,
    resolve_model_dir,
    write_zip,
)
from .tmdl import SemanticModel

EXIT_OK = 0
EXIT_DRIFT = 1
EXIT_ERROR = 2


class StylerError(click.ClickException):
    """A fatal error; exits with EXIT_ERROR so CI can tell it from drift."""

    exit_code = EXIT_ERROR


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, prog_name="pbi-plot-styler")
@click.argument(
    "report_dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)
@click.option(
    "--model",
    "model_dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help="Semantic-model folder. Default: resolved from the report's "
    "definition.pbir (datasetReference.byPath).",
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
    "--visual-type",
    "visual_types",
    multiple=True,
    help="visualType to restyle (repeatable). Default: "
    "lineClusteredColumnComboChart.",
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
    help="Hex color to add to the palette (repeatable). When set, colors "
    "are cycled per measure and --line-color is ignored.",
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
    "measure's line color.",
)
@click.option(
    "--label-transparency",
    type=int,
    default=None,
    help="Data-label background transparency, 0-100. Default: 20.",
)
@click.option(
    "--show-labels/--hide-labels",
    "show_labels",
    default=None,
    help="Turn data labels on or off. Default: on.",
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
    help="Also emit the styled report folder as OUT.zip. Combine with "
    "--dry-run to produce the archive without touching the source files.",
)
def main(
    report_dir: Path,
    model_dir: Path | None,
    config_path: Path | None,
    tables: tuple[str, ...],
    visual_types: tuple[str, ...],
    line_color: str | None,
    palette: tuple[str, ...],
    label_color: str | None,
    label_background: str | None,
    label_transparency: int | None,
    show_labels: bool | None,
    dry_run: bool,
    zip_path: Path | None,
) -> None:
    """Style every combo chart in REPORT_DIR from its field parameters.

    Reads the measures declared in the semantic model's field-parameter
    tables and rebuilds each targeted visual's line color, data labels,
    and data-label backgrounds - deterministically and idempotently.
    """
    if config_path is None:
        default_config = Path.cwd() / DEFAULT_CONFIG_FILENAME
        if default_config.is_file():
            config_path = default_config

    try:
        config = build_config(
            config_path,
            field_parameter_tables=tuple(tables) or None,
            visual_types=tuple(visual_types) or None,
            line_color=line_color,
            palette=tuple(palette) or None,
            label_color=label_color,
            label_background=label_background,
            label_transparency=label_transparency,
            show_labels=show_labels,
        )
    except ConfigError as exc:
        raise StylerError(str(exc)) from exc

    try:
        resolved_model = model_dir or resolve_model_dir(report_dir)
        model = SemanticModel.load(resolved_model)
        measure_keys = model.field_parameter_measures(
            config.field_parameter_tables
        )
    except (FileNotFoundError, LookupError) as exc:
        raise StylerError(str(exc)) from exc

    if not measure_keys:
        raise StylerError(
            f"no measures resolved from field-parameter tables "
            f"{list(config.field_parameter_tables)} in {resolved_model}, so "
            f"there is nothing to style. The tables exist, but none of "
            f"their NAMEOF references match a measure declared in the "
            f"model. Check that the configured tables reference measures, "
            f"not only columns."
        )

    click.echo(f"Model:    {resolved_model}")
    click.echo(f"Measures: {len(measure_keys)} drive the styling")

    try:
        changes = plan_changes(report_dir, measure_keys, config)
    except FileNotFoundError as exc:
        raise StylerError(str(exc)) from exc

    pending = [c for c in changes if c.changed]
    if not changes:
        click.echo("No targeted visuals found.")

    if dry_run:
        for change in pending:
            click.echo()
            click.echo(change.unified_diff(report_dir), nl=False)
        if changes:
            click.echo(
                f"\n{len(pending)}/{len(changes)} visual(s) would change."
                if pending
                else f"\nAll {len(changes)} visual(s) already styled."
            )
    else:
        written = apply_changes(changes)
        if changes:
            for change in pending:
                rel = change.path.relative_to(report_dir).as_posix()
                click.echo(f"  styled {rel}")
            click.echo(
                f"\nRestyled {written}/{len(changes)} visual(s); "
                f"{len(changes) - written} already styled."
            )

    if zip_path is not None:
        write_zip(report_dir, changes, zip_path)
        click.echo(f"Wrote {zip_path}")

    if dry_run and pending:
        sys.exit(EXIT_DRIFT)


if __name__ == "__main__":  # pragma: no cover
    main()

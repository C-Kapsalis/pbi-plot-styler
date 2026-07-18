# Contributing to pbi-plot-styler

`pbi-plot-styler` is a Python CLI that restyles Power BI PBIP reports by
declaration: it reads the measures your semantic model's field-parameter
tables expose and rebuilds the series colors and data-label formatting of
every targeted combo chart, deterministically and idempotently. This guide
covers how to set up a dev environment, how the code is laid out, how the
styling pipeline works, and how to get a change merged.

## Dev setup

Requires Python 3.10 or later.

```bash
git clone <your-fork-url> pbi-plot-styler
cd pbi-plot-styler
python -m venv .venv
# bash / macOS / Linux
source .venv/bin/activate
# PowerShell / Windows
.venv\Scripts\Activate.ps1

# Editable install with the dev extras (pytest)
pip install -e ".[dev]"

# Run the test suite
pytest
```

The editable install puts the `pbi-plot-styler` console command on your PATH
(defined by `[project.scripts]` in `pyproject.toml`), so you can exercise your
changes end to end against the bundled example:

```bash
pbi-plot-styler examples/coffee-roastery/Roastery.Report --dry-run
```

`pyproject.toml` sets `pythonpath = ["src"]` and `testpaths = ["tests"]`, so
`pytest` finds the package and the tests with no extra flags. The build backend
is `hatchling`; runtime dependencies are `click` (plus `tomli` on Python 3.10,
where `tomllib` is not yet in the standard library).

## Project layout

```
src/pbi_plot_styler/
  __init__.py     — package metadata (__version__)
  cli.py          — Click command; argument/option parsing, output, exit codes
  config.py       — StylerConfig dataclass, TOML loading, flag/file/default merge
  report.py       — report traversal + the visual.json rewrite (dataPoint[] / labels[])
  tmdl.py         — minimal TMDL parsing: measure inventory + NAMEOF resolution
tests/
  conftest.py     — fixtures (a disposable copy of the roastery project), EXPECTED_KEYS
  test_cli.py     — end-to-end CLI: apply, dry-run, config, overrides, zip, byte fidelity
  test_restyle.py — formatting rebuild: entry shapes, palettes, determinism, idempotency
  test_tmdl.py    — TMDL parsing: measure inventory, field-parameter reference resolution
  fixtures/roastery/ — a small PBIP project used by the tests
examples/coffee-roastery/ — a complete, openable PBIP demo (see its README)
docs/             — tutorials / reference / explanation
```

## How the styling pipeline works

A run flows in one direction: **TMDL → measure keys → restyled visuals**.

1. **Resolve the model** (`report.resolve_model_dir`). The report's
   `definition.pbir` is read and its `datasetReference.byPath.path` points at
   the paired `*.SemanticModel` folder. `--model` overrides this.
2. **Parse the TMDL** (`tmdl.SemanticModel.load`). Every
   `definition/tables/*.tmdl` is scanned for its `table` declaration and its
   `measure` declarations, building a `table -> {measure names}` inventory.
   Only TMDL models are supported; TMSL/`model.bim` is not.
3. **Resolve measure keys** (`tmdl.SemanticModel.field_parameter_measures`).
   The configured field-parameter tables' partitions are scanned for
   `NAMEOF ( [Measure] )` / `NAMEOF ( 'Table'[Measure] )` references. Comments
   are stripped first (`strip_dax_comments`), so retired measures parked as
   commented-out tuples are ignored. A reference counts only when the model
   actually declares a measure by that name (column/dimension references are
   skipped). The result is a **sorted** list of `"Table.Measure"` keys — the
   sort makes output deterministic.
4. **Plan the rewrite** (`report.plan_changes`). Every `visual.json` under
   `definition/pages/**` is read as raw bytes; visuals whose `visualType` is
   not in the configured targets are skipped. For each target,
   `report.restyle_visual` returns a deep copy with two arrays under
   `visual.objects` rebuilt from scratch off the sorted measure list:
   - **`dataPoint[]`** — one entry per measure, binding the series `fill`
     (line and columns) to a hex color, selected via
     `selector.metadata = "<Table>.<Measure>"`.
   - **`labels[]`** — a leading no-selector entry (`show`, text `color`,
     `enableBackground: true`), then one background entry per measure.

   Because both arrays are regenerated wholesale, the operation is
   deterministic, idempotent, and self-healing (stale entries for
   renamed/retired measures disappear).
5. **Apply or diff** (`cli.main`). Default mode writes changed visuals in
   place with `write_bytes` (never text mode — that would rewrite LF to CRLF
   on Windows and churn bytes outside the two arrays; the source trailing-
   newline convention is preserved too). `--dry-run` prints a unified diff and
   writes nothing. `--zip OUT.zip` also emits the styled report as an archive.

Exit codes are CI-grade: `0` clean, `1` drift (dry-run only), `2` error.

## Adding a config knob or a styling rule

Configuration has a single merge path (`config.build_config`), with precedence
**CLI flags > config file > built-in defaults**. To add a new knob, touch these
in order:

1. **`config.py`** — add a field to the `StylerConfig` dataclass with a default
   (add a `DEFAULT_*` constant for it), validate it in `StylerConfig.validate`
   (reuse `_require_hex` for colors), and map its TOML key in
   `load_config_file` (under the right `[tables]` / `[targets]` / `[style]`
   section).
2. **`cli.py`** — add the matching `@click.option`, then pass it into the
   `build_config(...)` call. Options default to `None` so that an unset flag
   never masks a config-file value.
3. **`report.py`** — consume the new field in `restyle_visual` (or its
   `datapoint_entry` / `labels_*` helpers) to actually change the output.

To add a **new styling rule** (e.g. rebuild another `visual.objects` array),
add a builder helper alongside `datapoint_entry` / `labels_entry` and wire it
into `restyle_visual`. Keep rules **deterministic and idempotent**: build the
array from scratch off the sorted `measure_keys` rather than mutating what is
already there, so re-runs stay a no-op and stale entries heal.

Add or update tests for any change: `test_tmdl.py` for parsing/resolution,
`test_restyle.py` for the rewrite shape and determinism, `test_cli.py` for the
flag/config surface and byte fidelity. The tests work off a disposable copy of
`tests/fixtures/roastery` (see `conftest.py`); `EXPECTED_KEYS` there is the
canonical sorted measure-key list.

## Check before you open a PR

```bash
pytest
pbi-plot-styler examples/coffee-roastery/Roastery.Report --dry-run
```

`pytest` must be green. The `--dry-run` on the example is a quick smoke test:
because the example ships deliberately unstyled it should print a diff and exit
`1` on a clean checkout — run it before and after your change to confirm the
tool still produces sensible output. Keep the change focused; do not modify the
`examples/` project or its committed report as part of an unrelated change.

## Commit and PR conventions

- Write imperative, present-tense commit subjects ("Add label-outline knob",
  not "Added" / "Adds"). Keep the subject under ~72 characters and explain the
  *why* in the body when it is not obvious.
- One logical change per commit; keep formatting-only churn out of feature
  commits.
- Open a PR against the default branch with a clear description of the problem
  and the approach, the commands you ran to verify (`pytest`, a `--dry-run`),
  and a note on any user-facing change to the CLI/config surface. Update the
  relevant docs (`README.md`, `docs/`, `RELEASE-NOTES.md`) when behavior
  changes.

## Reporting issues

File issues with: the exact command you ran, the observed output (including the
exit code), what you expected, your OS and Python version, and — if the problem
is parsing- or rewrite-related — a minimal snippet of the field-parameter TMDL
or the `visual.json` involved. If you can reproduce against
`examples/coffee-roastery`, say so; a shared reproduction is the fastest path
to a fix.

## License

By contributing you agree that your contributions are licensed under the
project's [MIT License](LICENSE) (Copyright © 2026 Christoforos Kapsalis).

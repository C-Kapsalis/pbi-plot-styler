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
  __init__.py     : package metadata (__version__)
  check.py        : the `check` command's integrity checks, surgical fixes, baselines
  cli.py          : Click group (`style`, the default, and `check`); options, output, exit codes
  config.py       : StylerConfig dataclass, TOML loading, flag/file/default merge, colors
  report.py       : report discovery + the owned-entries visual.json rewrite
  tmdl.py         : minimal TMDL parsing: tables, measures, columns, hierarchies,
                    field-parameter catalogs, palette slots, reference resolution
tests/
  conftest.py     : fixtures (disposable copies of the test projects), EXPECTED_KEYS
  test_check.py   : `check`: one injected defect per check id, --fix, baselines
  test_cli.py     : end-to-end CLI: apply, dry-run, config, overrides, zip, byte fidelity
  test_preserve.py : owned-entries merge, asserted against the brewbar ground truth
  test_restyle.py : formatting rebuild: entry shapes, palettes, determinism, idempotency
  test_tmdl.py    : TMDL parsing: inventory, field-parameter catalogs, slots, comments
  fixtures/roastery/ : a small PBIP project used by the tests
  fixtures/brewbar/  : hand-tuned formatting, bookmarks, a field-parameter-bound columns role
examples/coffee-roastery/ : a complete, openable PBIP demo (see its README)
```

The full documentation (tutorials, reference, explanation) lives in the
separate `pbi-plot-styler-documentation` repository, published on Read the
Docs; see [README.md](README.md#documentation).

## How the styling pipeline works

A run flows in one direction: **TMDL → measure keys → restyled visuals**.

1. **Find the reports and their models** (`report.discover_reports`,
   `report.resolve_model_dir`). The path is a `*.Report` folder or any folder
   holding `*.Report` folders at any depth. Each report's `definition.pbir`
   is read and its `datasetReference.byPath.path` points at the paired
   `*.SemanticModel` folder; each model is loaded once. `--model` overrides
   this.
2. **Parse the TMDL** (`tmdl.SemanticModel.load`). Every
   `definition/tables/*.tmdl` is scanned for its `table` declaration and its
   `measure`, `column` and `hierarchy` declarations.
   Only TMDL models are supported; TMSL/`model.bim` is not.
3. **Resolve measure keys** (`tmdl.SemanticModel.field_parameter_measures`).
   The configured field-parameter tables' partitions are scanned for
   `NAMEOF ( [Measure] )` / `NAMEOF ( 'Table'[Measure] )` references. Comments
   are stripped first (`strip_dax_comments`), so retired measures parked as
   commented-out tuples are ignored. A reference counts only when the model
   actually declares a measure by that name (column/dimension references are
   skipped). The result is a **sorted** list of `"Table.Measure"` keys: the
   sort makes output deterministic. Separately, `palette_slots` gives each
   measure a stable color slot from the field parameter's sort ordinals.
4. **Plan the rewrite** (`report.plan_changes`). Every `visual.json` under
   `definition/pages/**` is read as raw bytes; visuals whose `visualType` is
   not in the configured targets are skipped. The measures of the
   `exclude_current_roles` roles are computed per visual
   (`report.role_measure_keys`). `report.restyle_visual` then returns a deep
   copy in which only the **owned** entries change: the
   `selector.metadata = "<Table>.<Measure>"` entries of styled measures, and
   inside them only `fill` (`dataPoint[]`) and `backgroundColor` /
   `backgroundTransparency` (`labels[]`), merged over the existing entry so
   sibling properties survive. No-selector defaults, `selector.data`
   entries, and the entries of excluded measures are kept verbatim and in
   order; `_assert_preserved` raises `RestyleInvariantError` if any of them
   changed. Entries of retired measures are dropped, so the operation is
   deterministic, idempotent, and self-healing.
5. **Apply or diff** (`cli.style`). Default mode writes changed visuals in
   place with `write_bytes` (never text mode: that would rewrite LF to CRLF
   on Windows and churn bytes outside the owned entries; the source line
   endings and trailing-newline convention are preserved too, and a visual
   already in style is not rewritten at all). `--dry-run` prints a unified diff and
   writes nothing. `--zip OUT.zip` also emits the styled report as an archive.

Exit codes are CI-grade: `0` clean, `1` drift (dry-run only), `2` error.

The `check` command (`check.check_report`) is independent of styling: it
walks `report.json`, `page.json`, `visual.json` and bookmark files and emits
`Finding`s with stable ids (the table is in `check.py`'s docstring). To add a
check, give it a new id in `CHECKS` (never reuse or renumber one: baselines
key on it), use a location subject that does not depend on array indices,
and add a test that injects exactly that defect into a copy of the brewbar
fixture. A fix must be a surgical text edit verified by parsing both sides,
like `fix_bookmark_text`.

## Adding a config knob or a styling rule

Configuration has a single merge path (`config.build_config`), with precedence
**CLI flags > config file > built-in defaults**. To add a new knob, touch these
in order:

1. **`config.py`**: add a field to the `StylerConfig` dataclass with a default
   (add a `DEFAULT_*` constant for it), validate it in `StylerConfig.validate`
   (reuse `_require_hex` for colors), and map its TOML key in
   `load_config_file` (under the right `[tables]` / `[targets]` / `[style]`
   section).
2. **`cli.py`**: add the matching `@click.option`, then pass it into the
   `build_config(...)` call. Options default to `None` so that an unset flag
   never masks a config-file value.
3. **`report.py`**: consume the new field in `restyle_visual` (or its
   `datapoint_entry` / `labels_*` helpers) to actually change the output.

To add a **new styling rule** (e.g. style another `visual.objects` array),
add a builder helper alongside `datapoint_entry` / `labels_entry` and wire it
into `restyle_visual`. Keep rules **deterministic and idempotent**, and follow
the owned-entries rule: change only the properties you own, merge into the
existing entry instead of replacing it, emit owned entries in sorted
`measure_keys` order, and extend `_assert_preserved` to cover everything you
keep. Test preservation against fixture ground truth (literal expected
entries), never only against the tool agreeing with itself.

Add or update tests for any change: `test_tmdl.py` for parsing/resolution,
`test_restyle.py` / `test_preserve.py` for the rewrite shape, preservation and
determinism, `test_check.py` for checks, `test_cli.py` for the flag/config
surface and byte fidelity. The tests work off disposable copies of
`tests/fixtures/roastery` and `tests/fixtures/brewbar` (see `conftest.py`); `EXPECTED_KEYS` there is the
canonical sorted measure-key list.

## Check before you open a PR

```bash
pytest
pbi-plot-styler examples/coffee-roastery/Roastery.Report --dry-run
```

`pytest` must be green. The `--dry-run` on the example is a quick smoke test:
because the example ships deliberately unstyled it should print a diff and exit
`1` on a clean checkout: run it before and after your change to confirm the
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
  and a note on any user-facing change to the CLI/config surface. Update
  `README.md`, `RELEASE-NOTES.md`, and the relevant page in
  `pbi-plot-styler-documentation` when behavior changes.

## Reporting issues

File issues with: the exact command you ran, the observed output (including the
exit code), what you expected, your OS and Python version, and, if the problem
is parsing- or rewrite-related, a minimal snippet of the field-parameter TMDL
or the `visual.json` involved. If you can reproduce against
`examples/coffee-roastery`, say so; a shared reproduction is the fastest path
to a fix.

## License

By contributing you agree that your contributions are licensed under the
project's [MIT License](LICENSE) (Copyright © 2026 Christoforos Kapsalis).

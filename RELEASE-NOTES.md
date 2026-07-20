# Release notes

## Unreleased

### Fixed

- **A typo'd `plotstyler.toml` key or section used to be silently
  ignored.** `line-color` instead of `line_color` (matching the CLI
  flag's own hyphenated spelling), or `[Style]` instead of `[style]`,
  parsed fine and changed nothing, with no warning that the value was
  never read. Every section and key is now validated; an unknown one
  fails with a clear error naming it, before styling runs.

### Added

- **`--rename-table OLD=NEW`** (repeatable), and the matching
  `[tables] renames` config-file key. Renames a single default
  field-parameter table, leaving the other two default names in
  place, unlike `--table`, which replaces the whole default trio the
  moment it is used once.
- **`--exclude-role NAME`** (repeatable), and the matching
  `[targets] exclude_current_roles` config-file key. When a measure
  is a member of the line's field-parameter table but is currently
  plotted on the columns via a different selector, Power BI's
  `selector.metadata` matches it by name regardless of which selector
  picked it, so the columns' current measure would otherwise get the
  line's styling too. `--exclude-role Y` reads whichever measure is
  presently bound to the columns (`Y`) role on each visual and leaves
  it out of that visual's styling; it re-reads the current binding on
  every run, so it follows the report if that selection changes.

## v0.1.0, 2026-07-18

First public release.

### Highlights

- **One command makes every combo chart presentation-ready.** Point
  `pbi-plot-styler` at a PBIP report folder and it rebuilds the series
  colors and data-label formatting of every targeted visual from the
  measures your semantic model's field-parameter tables declare.
- **Deterministic, idempotent, self-healing.** The same model and config
  always produce byte-identical output, re-running a styled report is a
  no-op, and stale entries for renamed or retired measures are discarded
  on every run.
- **CI-grade dry-run.** `--dry-run` prints a unified diff and exits `1`
  when any visual has drifted from the model, `0` when everything is in
  style, a ready-made pipeline gate.

### What it styles

For every `lineClusteredColumnComboChart` (configurable) in the report,
the tool regenerates exactly two arrays in `visual.json`:

- `dataPoint[]`, one series-fill entry per declared measure.
- `labels[]`, data labels on, text color, `enableBackground`, and one
  background entry per measure.

Everything else in the file is preserved byte for byte, including line
endings and the file's end-of-file convention.

### Configuration surface

Every knob is both a CLI flag and a `plotstyler.toml` key (flags win):
field-parameter table names, targeted visual types, line color or a
per-measure palette, label text color, label background color and
transparency, and labels on/off. `--model` overrides the semantic-model
folder when `definition.pbir` does not resolve to it, and `--zip` emits
the styled report as an archive. See the CLI reference in
`pbi-plot-styler-documentation` for the full table.

### Known limitations

- Only field-parameter tables saved as TMDL (`definition/tables/*.tmdl`)
  are read; TMSL/`model.bim` models are not supported.
- All measures are styled uniformly by design. A measure that needs
  bespoke formatting should live in a visual type outside the configured
  targets.
- Power BI applies per-measure formatting once per visual: projecting the
  same measure on both the column and the line axis leaves the line
  unstyled. Use a wrapper measure instead; see the "field-parameter
  reporting" explanation page in `pbi-plot-styler-documentation`.
- A report folder whose name begins with a dash must be passed as
  `./-Name.Report` (or after `--`) so it is not read as a flag.

### Install

```bash
pip install .
```

Requires Python 3.10 or later. Runtime dependencies: `click` (plus
`tomli` on Python 3.10).

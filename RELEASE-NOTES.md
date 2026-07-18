# Release notes

## v0.1.0 — 2026-07-18

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
  style — a ready-made pipeline gate.

### What it styles

For every `lineClusteredColumnComboChart` (configurable) in the report,
the tool regenerates exactly two arrays in `visual.json`:

- `dataPoint[]` — one series-fill entry per declared measure.
- `labels[]` — data labels on, text color, `enableBackground`, and one
  background entry per measure.

Everything else in the file is preserved byte for byte, including line
endings and the file's end-of-file convention.

### Configuration surface

Every knob is both a CLI flag and a `plotstyler.toml` key (flags win):
field-parameter table names, targeted visual types, line color or a
per-measure palette, label text color, label background color and
transparency, and labels on/off. `--model` overrides the semantic-model
folder when `definition.pbir` does not resolve to it, and `--zip` emits
the styled report as an archive. See the
[CLI reference](docs/reference/cli.md) for the full table.

### Known limitations

- Only field-parameter tables saved as TMDL (`definition/tables/*.tmdl`)
  are read; TMSL/`model.bim` models are not supported.
- All measures are styled uniformly by design. A measure that needs
  bespoke formatting should live in a visual type outside the configured
  targets.
- Power BI applies per-measure formatting once per visual: projecting the
  same measure on both the column and the line axis leaves the line
  unstyled. Use a wrapper measure instead — see
  [Field-parameter reporting](docs/explanation/field-parameter-reporting.md).
- A report folder whose name begins with a dash must be passed as
  `./-Name.Report` (or after `--`) so it is not read as a flag.

### Install

```bash
pip install .
```

Requires Python 3.10 or later. Runtime dependencies: `click` (plus
`tomli` on Python 3.10).

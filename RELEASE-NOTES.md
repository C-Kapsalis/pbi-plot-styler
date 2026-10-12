# Release notes

## v1.1.0, 2026-10-12

Version metadata note: the v1.0.0 release (tagged `v1.0.0-stable`)
mistakenly reported version `0.1.0` in `pyproject.toml` and
`pbi_plot_styler.__version__`, so `pbi-plot-styler --version` printed
`0.1.0`. From this release the package metadata matches the tag.

### Changed

- **Palette colors follow the field parameter's order.** With `palette`
  set, each measure takes the color of its slot in the field-parameter sort
  order (tables in configured order, first registration wins) instead of
  its alphabetical position. Adding or renaming a measure no longer repaints
  the others. Existing palette users will see colors move once.
- **Existing label settings are respected.** On a visual that already has
  a no-selector `labels` entry, the styler only ensures `enableBackground`;
  `show` and the label text `color` are changed only when `show_labels` or
  `label_color` is set explicitly (flag or config). Likewise a measure's
  existing `backgroundTransparency` is kept unless `label_transparency` is
  set explicitly.
- **No targeted visuals is an error.** A run that finds no report, or no
  visual of a targeted type, exits `2` instead of `0`, so a misconfigured CI
  gate cannot pass by checking nothing.
- The CLI is now a command group. `pbi-plot-styler REPORT_DIR [OPTIONS]`
  works as before (it runs the default `style` command);
  `pbi-plot-styler style REPORT_DIR` is the explicit form.

### Added

- **`pbi-plot-styler check PATH`**: read-only integrity checks with stable
  ids, text or `--json` output, and exit codes `0`/`1`/`2`. It checks that
  every field reference, `queryRef` and `selector.metadata` in visuals,
  pages, report filters and bookmarks resolves in the paired model
  (`BND001`, `BND002`); that bookmark `options` keys are in the allowed set
  (`BMK001`) and `howCreated`, `ComparisonKind` and `Version` are integers
  (`BMK002`); that bookmarks point at existing pages and visuals and
  `bookmarks.json` at existing bookmark files (`BMK003` to `BMK005`); that
  field-parameter slot ranges do not overlap or overflow (`FPM001`,
  `FPM002`); that theme files exist (`THM001`, warning); and that every
  file is valid JSON (`JSN001`). `--fix` repairs `BMK001` and `BMK002` with
  surgical, verified text edits. `--baseline FILE` and `--update-baseline`
  let a team adopt the gate on a report with known findings.
- **Folders of reports.** `REPORT_DIR` (and `check PATH`) may be any folder
  containing one or more `*.Report` folders at any depth; each report uses
  its own paired model.
- **Color pins**: `[style.colors]` in `plotstyler.toml`, or
  `--color "Table.Measure=#HEX"`, fix one measure's color.
- **Theme colors**: `style.theme_color_id` / `--theme-color-id N`, with
  optional `style.theme_color_percent` / `--theme-color-percent P`, write a
  `ThemeDataColor` expression instead of a hex literal.
- **`--rename-table OLD=NEW`** (repeatable), and the matching
  `[tables] renames` config-file key. Renames a single default
  field-parameter table, leaving the other two default names in
  place, unlike `--table`, which replaces the whole default trio the
  moment it is used once.
- **`--exclude-role NAME`** (repeatable), and the matching
  `[targets] exclude_current_roles` config-file key. Power BI's
  `selector.metadata` matches a measure by name regardless of which
  selector picked it, so a measure the columns currently show would
  otherwise get the line's styling too. `--exclude-role Y` leaves the
  columns' measures out of styling on each visual and keeps their existing
  formatting; it re-reads the binding on every run.

### Fixed

- **Restyling no longer destroys formatting it does not own.** Earlier
  versions rebuilt `objects.dataPoint[]` and `objects.labels[]` from
  scratch, deleting the no-selector `dataPoint` default (the column render
  baseline), per-legend-value `selector.data` entries such as
  `showSeries: false`, hand-picked column colors, and hand-tuned properties
  next to the ones the tool sets. The styler now rewrites only the
  `selector.metadata` entries of the measures it styles, and inside those
  only `fill` and `backgroundColor`. Everything else is kept verbatim and in
  order: `[defaults] + [excluded measures] + [styled measures] +
  [data-scoped]`. A built-in invariant refuses to write if a preserved
  entry would change.
- **The columns' measures no longer inherit the line's styling when the
  columns are bound through a field parameter.** `--exclude-role Y` now also
  excludes every measure of a field parameter bound to that role, not only
  a directly bound measure.
- **Block comments are ignored.** A tuple parked inside `/* ... */` in a
  field-parameter partition no longer gets styled.
- **A typo'd `plotstyler.toml` key or section used to be silently
  ignored.** `line-color` instead of `line_color` (matching the CLI flag's
  own hyphenated spelling), or `[Style]` instead of `[style]`, parsed fine
  and changed nothing, with no warning that the value was never read. Every
  section and key is now validated; an unknown one fails with a clear error
  naming it, before styling runs.
- **Byte fidelity.** A visual that is already in style is never rewritten,
  and CRLF line endings are preserved when one is.

## v1.0.0, 2026-07-18

First public release (tagged `v1.0.0-stable`; its package metadata
reported `0.1.0`).

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
the tool regenerated exactly two arrays in `visual.json` (from v1.1.0 it
rewrites only the per-measure entries it owns):

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

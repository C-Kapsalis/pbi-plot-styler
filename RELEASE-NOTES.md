# Release notes

## Unreleased

### Added

- **Canvas convention rules for `check`**, selected with `--rule SLUG`
  (repeatable; the default stays the `integrity` checks of v1.1.0). Each has
  stable ids and works with `--json`, `--baseline` and `--update-baseline`:
  - `slicer-gates`: `GAT001` (selector slicer on a visible canvas page
    without an active `[f-Slicer] > 0` filter), `GAT002` (bookmark capture of
    a selector slicer without it). `--fix` writes the gate on the table that
    declares the measure.
  - `slicer-mode-gates`: `GAT003` (gate for the slicer's mode absent or
    passive; dropdown needs `f-Slicer`, list needs `f-All`), `GAT004` (active
    gate on a table that does not declare it), `GAT005` (stale gate table
    references). `--fix` writes and repoints. Exit `2` when no sibling model
    declares both gate measures.
  - `category-filter`: `CAT001`, a menu bookmark does not set the
    analysis-category filter.
  - `theme`: `THM002` (no theme collection), `THM003` (warning, no custom
    theme), `THM004` (hex colour literals in `report.json`, with count and
    samples), `THM005` (no base or custom theme), `THM006` (base or custom
    theme missing).
  - `visual-position`: `POS001` (warning), a visual without x or y.
  - `y-combo`: `YCG001` (badly named `y<N>_combo_group`), `YCG002` (member
    outside its group).
  - `filter-panel`: `PNL001` (no `y_filters_group`), `PNL002` (warning, not a
    group). `--fix` renames the detected master group on the main page with
    its children's parent links and bookmark references.
  - `format-selector`: `FMT001`, the hidden, locked `z-Selector Format` =
    `Format` report filter is missing or incomplete (active when the model
    has that table). `--fix` writes the canonical filter, keeping its name.
  - `stale-placeholders`: `PLH001`, a visual or bookmark binds a
    blank-dimension placeholder its y-axis selector does not offer. `--fix`
    repoints it; ambiguous roles are skipped.
  - `answer-bookmarks`: `ABK000` (vacuity guard), `ABK001` (scoped
    bookmark), `ABK003` (matrix not captured or hidden), `ABK004` (rows not
    this bookmark's own, inherited fingerprint), `ABK005` (capture shape),
    `ABK006` (captured picker selects nothing), `ABK007` (category not
    pinned), `ABK008` (not under a submenu), `ABK009` (slot map), `ABK010`
    (row dimension without a dropdown filter), `PGW001` (raw measure in a
    parameter well), `PGW002` (navigator names a missing bookmark).
  - `bookmark-literals`: `BML001` (picker literal registered only in another
    selector), `BML002` (registered nowhere); `--only-display-names FILE`.
- **`check --summary`**: compliance with the four foundation rules
  (`slicer-gates`, `category-filter`, `theme`, `filter-panel`); never fails.
- **`check --report NAME` and `--model-name NAME`** filters, and a default
  exclusion of the API-only report family (`M.Report`, `-M.Report`) from
  folder sweeps (`[canvas] exclude_reports`). A filter that matches nothing
  exits `2`.
- **`check --config FILE`** and the canvas sections of `plotstyler.toml`
  (`[canvas]`, `[gates]`, `[category]`, `[placeholders]`, `[panel]`,
  `[format_selector]`, `[answer_bookmarks]`); the JSON output gains `rules`
  and `skipped`.
- **`style --rebind-stale-line`** (opt-in): a line (`Y2`) measure
  projection whose name the model no longer declares is pointed at the
  current measure (leading symbols stripped, then an exact name or a single
  case-insensitive match in the same table), `queryRef` updated, reported as
  `rebound` (`would rebind` under `--dry-run`, which then exits `1`).
- **`[style] label_default_properties`** (the seeded no-selector `labels`
  entry) and **`[style] touch_existing_label_default`** (`false` leaves an
  existing one exactly as found); **`[targets] line_role` / `column_role`**.
- **`colors sync` / `colors reset`**: one colour per measure from the model's
  palette measure, on column series, matrix columns and existing bookmark
  overrides; exit `0` changes, `2` none, `3` invalid input.
- **`bookmarks build`**: answer bookmarks rendered from a working base
  bookmark (picks, matrix and chart captures, visibility, category, date,
  drill level), `--keep-ids` re-render, `--legacy-layout`, `--dry-run`.
- **`rename-measure`** and the `pbi_plot_styler.rename` module
  (`report_roots`, `count_tree`, `rewrite_tree`, `count_measure_refs`,
  `rename_measure`): a report-side measure rename that also follows saved
  selections, cached display items, projection labels and value maps, with a
  dry-run count equal to the rewrite count.
- **`rename-label`**: rename a field-parameter row label in the selector
  tables and every report that remembers it.
- **`pbi_plot_styler.canvas`**: canvas pages, selector slicers and the
  settings the rules share.
- Documentation: `docs/convention-rules.md`, `docs/commands.md`.

### Changed

- **STRICTER: `FPM001` reports more overlaps.** A parameter that claims a
  slot it already claimed is now a finding; each claim is paired with the
  most recent earlier claimant of the slot (a third claimant is paired with
  the second, not the first); and each overlapping slot is its own finding
  (subject `role:slot:A|B`, previously `role:A|B`). Reports with overlaps can
  show more `FPM001` findings than before; a baseline recorded with v1.1.0
  needs `--update-baseline` for those entries.
- **STRICTER: `slicer-gates` checks bookmark captures too** (`GAT002`), not
  only the slicer visuals.
- `plotstyler.toml` accepts the sections of `check` and `bookmarks build`
  next to `[tables]`, `[targets]` and `[style]`; `style` ignores them. An
  unknown section is still an error.
- A missing `--baseline` file stays a usage error (exit `2`).

### Fixed

- `rename-measure` no longer renames the `queryRef`, `nativeQueryRef` or
  label of a column projection whose column shares the measure's name.
- `rename-measure` finds and writes names with an apostrophe or a closing
  bracket inside saved selection literals in their escaped form.
- `rename-measure` keeps each rewritten file's byte-order mark and line
  endings (CRLF stays CRLF).

### Notes on choices made where the specs left room

- The convention rules run only when named with `--rule`; a bare `check`
  is unchanged.
- With `--rebind-stale-line`, the column role (`Y`) counts as column side
  (never styled, its entries kept) unless `--exclude-role` is given, as the
  combo-line convention requires.
- Fixers keep each file's own conventions (BOM, CRLF, final newline) and
  write only files whose content changes; the source specs asked for a
  final newline on every rewritten file.
- Generated gate filter names are a stable hash of the slicer and measure
  instead of random characters, so reruns and fixer order give identical
  files.
- Answer-bookmark findings that can occur several times per bookmark
  (`ABK004` fingerprints, `ABK005`, `ABK006`, `ABK009`) add a suffix to the
  display-name subject so each is its own finding.
- `bookmarks build` has no built-in well map: the `[bookmarks] wells` table
  lists the pickers of each well (the ported fixture maps the matrix values
  to one picker, where the spec's default named three, because its entries
  pick the same measure in two pickers of that well). Pickers an entry does
  not mention keep the base bookmark's selection. The legacy layout empties
  unmentioned pickers but does not re-sync the values slicers to the first
  pick.

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

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
  - `visual-position`: `POS001`, a visual without x or y (an error).
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
  overrides; exit `0` written or nothing to do, `1` a dry run found changes,
  `2` invalid input.
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

- **The field parameters are detected from the model, not from their names.**
  With no `--table` and no `[tables] field_parameters` in the config, the
  tool detects the model's field parameters from its TMDL: a calculated
  table whose column carries `extendedProperty ParameterMetadata` and whose
  rows are `NAMEOF(...)` tuples. A parameter called `Bar Metrics` is in the
  set; a table called `x-Selector 1` that carries no parameter metadata is
  not. The name patterns (`x-*`, `y-*`) only rank and label the detected
  tables; they never replace the detection.

  Each detected parameter is classified by what its rows point at: columns
  make a **dimension** parameter, measures make a **metric** one, and a mix
  is flagged. The measures the styling drives come from the metric
  parameters; the column wells and the excluded roles work on the whole
  detected set, so a Y role bound through a parameter the user did not
  configure still excludes that parameter's whole catalog (the v1.1.0
  behaviour). An explicit `--table` or config list still restricts the
  expansion, as in the original.

  The command prints one line naming the tables it uses:
  `Field parameters: <names> (dimension: ...; metric: ...)`, or
  `Field parameters: <names> (explicit)` when the list was given.
- **STRICTER: `FPM001` reports more overlaps.** A parameter that claims a
  slot it already claimed is now a finding; each claim is paired with the
  most recent earlier claimant of the slot (a third claimant is paired with
  the second, not the first); and each overlapping slot is its own finding.
  The subject stays `role:A|B`; the slot is part of the location
  (`...::role:A|B#slotN`), so each slot is baselined on its own. Reports with
  overlaps can show more `FPM001` findings than before; a baseline recorded
  with v1.1.0 needs `--update-baseline` for those entries.
- `check --fix --dry-run` prints a unified diff of every change the fixers
  would make and writes nothing (exit `1` when something would change).
  `--dry-run` without `--fix` is a usage error.
- **STRICTER: `slicer-gates` checks bookmark captures too** (`GAT002`), not
  only the slicer visuals.
- **STRICTER: `bookmarks build` stops on what it cannot apply.** A
  `date_filter` other than `this_year` (or `null`) is an error; a chart or
  legacy picker capture the base lacks is an error rather than a skip; a
  pick repeated in a chart well is an error as in a matrix well. Every
  build failure exits `2` and writes no file at all.
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
- Files saved on Windows: every file the tool reads (`definition.pbir`,
  `visual.json`, bookmarks, TMDL, `plotstyler.toml`, builder configs, the
  `bookmarks build` entries file, `--only-display-names`, baselines) is
  accepted with or without a UTF-8 byte-order mark and with CRLF or LF.
  Every writer keeps the existing file's BOM and line endings, including
  `style`, the `check --fix` fixers and `bookmarks build --keep-ids`.
  Previously a BOM in `definition.pbir` made the model unresolvable and a
  BOM in `visual.json` made `style` skip the visual.
- A semantic model that `definition.pbir` (or `--model`) points at but that
  cannot be loaded is now an `MDL001` error (exit `1`) on the report, and the
  rules that need the model say it could not be loaded. Previously they were
  skipped with a note that blamed a missing table. A report with no local
  model is still only a note.
- `check --fix` over several reports checks every report's fixer
  prerequisites before writing anything; if a fixer still fails part-way,
  the error lists the changes already written instead of claiming nothing
  changed.
- `slicer-mode-gates` uses the report's own model (`definition.pbir` or
  `--model`) like every other rule, so nested report folders resolve.
- `--update-baseline` combined with `--rule`, `--report` or `--model-name`
  rewrites only the entries of that scope; entries of other rules and
  reports are kept.
- `--summary` no longer reports a rule (or the run) as compliant while it has
  error findings.
- `colors sync` / `colors reset` exit codes follow the other commands: `0`
  written or nothing to do, `1` a dry run found changes, `2` invalid input
  (previously `2` meant "no changes" and `3` invalid input).
- `colors` reads a palette offset written with a minus sign
  (`MOD ( _order - 1, n )`); it was read as offset 0, shifting every colour.
  A first `MOD` argument other than `<order>`, `<order> + n` or
  `<order> - n` is now rejected with exit `2`.
- `bookmarks build` without `--group` registers each new bookmark as a
  top-level entry of `bookmarks.json` (created if missing), so Power BI lists
  it; previously such bookmarks were written but not registered.
- `bookmarks build` row mirroring: an entry that sets one row dropdown
  itself still has its other row picks mirrored into the remaining
  dropdowns (previously any explicit dropdown stopped all mirroring). A
  dropdown that receives no row keeps the base bookmark's pick, so no
  captured dropdown selects nothing (`ABK006`). The legacy layout does not
  mirror rows.
- `bookmarks build` slot expressions name the field parameter's display
  column (the column named like the table), not the hidden fields column the
  picker slicer filters on, in both layouts.
- `bookmarks build` wells take only the entry's own picks (plus mirrored
  rows): a picker the entry does not mention keeps its saved selection on
  its slicer but no longer feeds the matrix or chart wells, so base
  placeholders cannot cause a "picked twice" error. Each picker of a well
  with projections gets a slot, with length 0 when it has no picks, and a
  rewritten chart role gets a fresh slot map.
- `bookmarks build --legacy-layout` edits the matrix capture in place: only
  the Rows and Values projections, their slots, the first sort entry, the
  active rows (now all rows) and the first container-level filter (pointed
  at the first measure) change; display mode, expansion states, prototype
  query, other roles, later sort entries and other slot keys are kept. A
  matrix captured only under a stale id is moved to the configured id with
  a note. Without `target_visuals` the bookmark is scoped to the matrix. The
  category filter is also found in the page's `byName` map, and a base
  without one is left unchanged instead of failing.
- `bookmarks build` writes non-ASCII text in bookmark files as UTF-8, not
  as `\u` escapes.
- `bookmarks build`: the default `calendar_hierarchy` is `Calendar
  Hierarchy`, and the date filter's calendar alias is the table's first
  character (`_` for `__Calendar`).
- `bookmarks build`: an entry may name its own `base`; `clear_filters`
  applies to every built bookmark, not only re-rendered ones; a picker named
  with an empty list keeps its In condition with no values and an empty
  cached list (legacy layout: no conditions, empty cached list);
  `matrix_sort` also accepts the flat `{table, column, direction, kind}`
  form and a direction written as text; a `null` or empty
  `analysis_category` or `drill_level`, and a `null` `date_filter`, leave the
  base unchanged.
- `bookmarks build --keep-ids` registers only the bookmarks it creates; a
  kept bookmark keeps its place in `bookmarks.json` (it was re-added at the
  top level when no group was given). Two existing bookmarks sharing the
  entry's display name are an error naming both. Each written line says
  whether the id was kept or new and shows the display name.
- `bookmarks build` ignores entry keys it does not know, as earlier builder
  configs expect (they were rejected).
- `bookmarks build --legacy-layout` handles the values slicers: the
  `[bookmarks] pickers` key `y_values_slicer_<N>` (N = 2..6) names the slicer
  that lists the values of the dimension picked in `y_selector_<N>`. Its
  preselection is always cleared, and when `y_selector_<N>` has picks its
  column (first `Values` projection, first active `Values` entry and every
  column `filters.byExpr` expression) becomes that picker's first pick. A
  values slicer is never a picker (an entry cannot pick it) and never holds
  a measure; one the base bookmark does not capture is skipped.
- `colors sync`: a matrix bound to the picker colours only the registered
  measures it projects (the field-parameter column adds none; there is no
  longer a whole-registry expansion); a matrix in scope only through
  `--all-visuals` or a bookmark uses the bookmark-needed measures. Registered
  entries outside that set turn black with the style flags.
- `colors sync` completes bookmark overrides: an existing `dataPoint` or
  `columnFormatting` array in a capture gains an entry for every needed
  registered measure it lacks (sorted by key; an array is never created), a
  matrix override blackens registered measures it does not need, a chart
  override keeps the base visual's line measures in its needed set, and
  overrides stored directly under `objects` (no `merge` wrapper) are found.
  Overrides are matched on page section and visual id, and the array follows
  the capture's own visual type.
- `colors sync` writes each colour exactly as the palette measure spells it
  (`#ABCDEF` stays upper case), so a report synced with upper-case colours
  is a no-op; reset still compares case-insensitively.
- `colors`: a visual uses the picker only when a value role (columns, line or
  values) carries it as a field parameter; a slicer on the picker or a matrix
  with the picker on rows is out of scope. `--visual-type` is applied first
  and silently; the "not supported" note appears only for a visual that
  would otherwise be in scope.
- `colors reset` reverts bookmark overrides too (wrapped or not), takes the
  repeatable `--visual-type`, loads the picker registry (same errors as
  `sync`) and reverts only registered measures; a matrix style flag is
  removed only when it is `true`.
- `colors` handles the plain `barChart` and `columnChart` types.
- `colors sync` prints a palette summary (picker, offset, modulus, slot
  count, registered measures), lists every series of each multi-series
  bookmark with its role, order and colour (line series included in the
  collision and unregistered checks), adds a re-spacing hint on collisions
  and ends with the number of entries rewritten and added.
- `answer-bookmarks`: `ABK000` (nothing matched the prefixes) can no longer
  be accepted by a baseline: `--update-baseline` never writes it, drops an
  existing entry for it and exits `1` while it occurs.
- `answer-bookmarks`: `ABK006` covers every main-page selector slicer, the
  row dropdowns and any configured slicer that a bookmark captures, not only
  the matrix parameters' slicers.
- `answer-bookmarks`: a row parameter whose slicer cannot be determined is a
  setup error (exit `2`) naming the candidates and `[answer_bookmarks]
  slicers`, instead of silently skipping the row checks; a matrix without a
  row parameter notes the two checks not run; a declared parameter with no
  known slicer is reported by name in both slot modes, and an empty slot map
  counts as missing in `all-roles` mode.
- `answer-bookmarks` and `bookmark-literals` report a bookmark file (and,
  for answer bookmarks, a main-page visual) that does not parse as `JSN001`,
  so the run fails; the navigator check compares against the bookmark files
  on disk.
- `--only-display-names` also accepts the `bookmarks build` entries file.
- `answer-bookmarks` and `bookmark-literals` print what they checked (answer
  bookmarks; bookmarks scanned, literals checked, literals resolved), also
  as `checked` in `--json`.
- `[answer_bookmarks] baseline` is honoured (it was accepted and ignored):
  without `--baseline`, a run that includes `answer-bookmarks` uses that
  file, relative to the config file; a missing file is a usage error.
- `healed` lists only accepted entries of the run's rules and reports, and
  is followed by a hint that `--update-baseline` locks the improvement in.
- `bookmark-literals` with no usable model on any report of the run exits
  `2` naming `--model` instead of passing.
- `ABK009` names the picks outside their slots; `ABK010` says when the
  dropdowns hold nothing; `--summary` prints a remediation hint under each
  finding (`fix` in `--json`); docs/convention-rules.md explains each
  `ABK` / `PGW` id.
- `PGW002` reads the navigator's selected bookmark only as a single-quoted,
  lower-case 20-character hex id, as Power BI writes it (it also accepted
  upper case and double quotes).
- BUGFIX (kept): the picker-literal registry normalises the table
  qualifier (`'Stores'[Region]` and `Stores[Region]` register the same row),
  and inherited fingerprints match non-ASCII text.
- `style` over a folder of reports (without `--model`) skips a report whose
  model cannot be resolved or loaded, or whose model styles no measure, with
  a `Skipped:` line, and counts it in the closing totals; the other reports
  are styled and decide the exit code. A single report or `--model` keeps
  the fatal error.
- `style --table` and `[tables] field_parameters` accept shell-style
  patterns (`x-*`), matched case-insensitively against the model's tables;
  a pattern that matches nothing is not an error by itself.
- `style` prints, per styled visual, the `dataPoint` and `labels` entry
  counts before and after and the column-side measures left unstyled, and
  ends with the number of rebinds and skipped reports.
- `style --seed-label-transparency N` (`[style] label_transparency_seed`)
  seeds a label background transparency only where a measure has none.
- `style` merges duplicate metadata entries of a styled measure from the
  last occurrence (it kept the first).
- `style` accepts a page folder or a `visual.json`: it finds the enclosing
  report and restyles only the visuals under that path.
- `check --rule filter-panel --fix` acts only when the check reports
  `PNL001`; on a report that already has the master group (even in a
  hash-named folder, with a nested sub-group covering the same tables) it
  writes nothing and notes that the group is already present. A candidate
  without a group object is never renamed. The change line names the old
  display name and the filter tables covered. Visual files it rewrites
  write non-ASCII text as `\u` escapes (the builder and the renames write it
  as UTF-8).
- `slicer-gates`: a slicer or capture is compliant when any filter bound to
  the gate measure is active (not only the first); the fixer repairs the
  first bound filter only when none is. A replaced bookmark gate's name
  equals its `byName` key (both gate rules), and a new bookmark gate gets
  the same name whichever gate fixer runs first. Gate filters always use the
  alias letter of `[gates] table`, whatever table declares the measure.
- Selector-table patterns match case-insensitively.
- `slicer-gates --fix` over several reports leaves a report whose model does
  not declare the gate measure unchanged, reports it as `REFUSED` and fixes
  the others (it stopped the whole run); the exit code comes from the
  re-check.
- `slicer-gates`: the optional name heuristic only adds findings; `--fix`
  never gates a slicer found only by name.
- BUGFIX (kept): `slicer-mode-gates` still repoints the `From` list of a
  stale gate filter, but only the alias a gate reference uses or an entry
  naming the stale table; unrelated sources are left alone.
- `--summary`: the theme row counts only `THM002`, `THM003` (warning) and
  `THM004` toward its compliance and the totals; `THM005` / `THM006` still
  run under `--rule theme`.
- `format-selector` reads the selected item as the first non-empty literal
  across the In rows; a report without `definition/report.json` is noted as
  not applicable (an unreadable or invalid one is still `FMT001`).
- `stale-placeholders` also reads the other JSON files of the bookmarks
  folder that hold exploration state (`bookmarks.json` excepted).
- `y-combo`: a member name needs at least one character after
  `y<N>_`.
- `rename-label` prints each pair's count first, right-aligned, then the
  quoted pair, and lists touched files in visiting order (model tables
  first) with `/` separators.
- `check` over a folder with no `*.Report` folder prints "nothing to check"
  and exits `0` (it exited `2`); a `--report` / `--model-name` filter that
  matches nothing still exits `2`. Reports are found in nested trees.
- `check --fix` exits from the re-check (documented in docs/commands.md).
- BUGFIX (kept): `style` keeps formatting entries whose selector shape it
  does not know, verbatim and in order, instead of dropping them.
- BUGFIX (kept): `rename-measure` follows dotted measure names, treats the
  new name literally and its dry-run count equals the rewrite count;
  `rename-label` is all or nothing.
- `bookmarks build` console output: one absolute file path per written
  bookmark (no registration or summary lines); with `--keep-ids`,
  `kept <id> <display name>` / `NEW  <id> <display name>`. Error texts follow
  the earlier builder scripts (`base bookmark <id> not found in <folder>`,
  `no base bookmark <id> in <folder>`, `bookmark group <group> not found`,
  `picker <key> (<id>) not captured by base bookmark`, `... row dimensions but
  only <m> dropdown filters (y-Selector 3..6) to carry them`, `base bookmark
  does not capture the Main Matrix`, `base bookmark has no RelativeDate filter
  slot`, `need >=3 measures, got <n>`, ...). Each starts with the entry's
  display name (the legacy limits with its analysis category). A field picked
  in two pickers of one well names both pickers and the role.
- `bookmarks build --self-test [--legacy-layout]` checks the builder against
  the report's base bookmark and prints `self-test PASS`.
- `bookmarks build` always writes `visualContainerGroups` on the built section
  and `projections` / `parameters` on a captured chart (default layout), and an
  empty cached list on a legacy picker it empties.
- `answer-bookmarks` text output follows the earlier page-state checker: a
  `bookmarks tested: <n> | failures: <m>` header (and a pass line), findings
  in check order per bookmark with page-level ones last, a header and a
  guidance block per run of one id, and its messages (`<name>: Main Matrix not
  captured (cannot be made visible)`, `<name>: not all-visuals targeting
  (null)`, the slot-map, dropdown and navigator sentences). `FPM001` /
  `FPM002` use the same wording (`<visual>/<role>: parameters A and B both
  claim slot n — ...`). The slot check now compares the Rows and the Values
  slots by default (`slot_mode = "all-roles"`), so a rows mismatch also
  reports the Rows slot map.
- `healed` is one line per id naming the count and the locations, with the
  `--update-baseline` hint in the same line.
- `bookmark-literals` prints `bookmarks checked: <n> | literals OK: <ok> |
  UNREGISTERED: <bad>` first and reports one finding per (bookmark, literal,
  reason), sorted, with the reason on its own line.
- Written DAX literals escape names: an apostrophe in a category value or
  the format item is doubled, and a field-parameter pick written by
  `bookmarks build` escapes apostrophes and closing brackets in its table and
  column names. `format-selector` compares against the escaped form, and
  `bookmark-literals` and every reader of saved picks unescape them (a
  `NAMEOF` column written with `]]` is read as one name).

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
  lists the pickers of each well (the example fixture maps the matrix values
  to one picker, because its entries pick the same measure in two pickers of
  that well). Pickers an entry does not mention keep the base bookmark's
  selection on their slicers (never in a well). The legacy layout empties
  unmentioned pickers.

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

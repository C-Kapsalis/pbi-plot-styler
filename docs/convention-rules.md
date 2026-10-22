# Canvas convention rules

`pbi-plot-styler check PATH` runs the `integrity` rule by default (bindings,
bookmarks, field-parameter slots, theme files; see the README). The rules on
this page check the conventions of the standard canvas page and run only when
named with `--rule SLUG` (repeatable). They share the `check` machinery:
stable ids, `--json`, `--baseline` / `--update-baseline`, exit codes `0` (no
new errors), `1` (new errors) and `2` (setup problem). `--update-baseline`
with `--rule`, `--report` or `--model-name` rewrites only that scope's
entries. `--fix --dry-run` prints the diff of every planned fix and writes
nothing. With several reports, `--fix` checks every report's prerequisites
before writing any.

Rules that cannot judge a report say so in a `skipped` list (text output:
`skipped` lines) instead of passing silently: no y-combo groups, no selector
slicer, an ambiguous placeholder, no paired model. A model that is referenced
but cannot be loaded is an `MDL001` error, not a skip.

## Vocabulary and settings

Every name a rule depends on is a setting with a generic default. Put the
sections you need in `plotstyler.toml` (read from the working directory, or
`--config FILE`); sections for `style` and `bookmarks build` can live in the
same file.

```toml
[canvas]
matrix_types = ["pivotTable", "matrix"]
combo_types = ["lineStackedColumnComboChart"]
excluded_page_fragments = ["cohort", "ltv"]
selector_tables = ["x-*", "y-*"]          # exact names or globs
measure_selector_tables = ["x-*"]
dimension_selector_tables = ["y-*"]
exclude_reports = ["M.Report", "-M.Report"]

[gates]
table = "f-Filters"                       # used in messages only
slicer_measure = "f-Slicer"
list_measure = "f-All"
mode_map = {Dropdown = "slicer_measure", Basic = "list_measure"}
name_heuristic = false

[category]
table = "z-Map Dimension-Measure Groupings"
column = "Analysis Category"

[placeholders]
blank_dimension_table = "#Report Measures"
template_slot_table = "Helper Measures"

[panel]
group_name = "y_filters_group"
filter_tables = ["y-Selector 3", "y-Selector 4", "y-Selector 5", "y-Selector 6"]
min_slicers = 6                           # main-page thresholds
min_combos = 1
min_matrices = 1

[format_selector]
table = "z-Selector Format"
column = "Selector Format"
item = "Format"
filter_name = "format_selector_filter"

[answer_bookmarks]
prefixes = ["Sales |", "Marketing |"]     # required for answer-bookmarks
main_page = "<page folder>"               # optional; discovered otherwise
matrix = "<visual id>"                    # optional; the page's only pivotTable
slicers = {"x-Selector 2" = "<visual id>"}  # optional per parameter
row_dropdowns = ["<visual id>"]           # optional; slicers on panel.filter_tables
inherited_fingerprints = []
submenu_prefix = "Submenu"
slot_mode = "all-roles"                   # or "values-only" (Values slots only)
baseline = "answer-floors.json"           # optional; used without --baseline,
                                          # relative to this file
```

Terms used below:

- **Canvas page**: a page with a visual of a `matrix_types` type and one of a
  `combo_types` type, whose display name contains none of the excluded
  fragments.
- **Main page**: the page with at least `min_slicers` slicers, a combo chart
  and a pivotTable (most slicers wins, then the larger folder name).
- **Selector slicer**: a slicer whose `Values` projection is a column of a
  selector table.
- **Semantic name**: a group's `visualGroup.displayName`, any other visual's
  `name`.

Report discovery: a `*.Report` folder is checked as is; any other folder is
searched at every depth. `--report NAME` keeps one report by folder name (with
or without `.Report`) and overrides `exclude_reports`; `--model-name NAME`
keeps reports whose `definition.pbir` points at `NAME.SemanticModel`. When
nothing matches, the run exits `2` and names the filter.

## slicer-gates

Every selector slicer stacks with others on the canvas; a visual-level filter
on `[f-Slicer] > 0` hides the ones that should not show. A gate is *active*
when one of its conditions compares the measure greater than 0 (kind 1 with
`0L`) or at least 1 (kind 2 with `1L`).

- `GAT001`: a selector slicer on a visible canvas page has no active gate.
- `GAT002`: a bookmark capture of a selector slicer on a canvas page has no
  active gate under `filters.byName`, so applying the bookmark removes it.

A slicer or capture is compliant when any filter bound to the gate measure is
active. Selector-table patterns (`[canvas] selector_tables`) match names
ignoring case. With `[gates] name_heuristic = true` (off by default) the
check also treats a slicer whose name contains both `slicer` and `selector`
as a selector slicer; this only adds findings and never makes `--fix` gate
such a slicer.

`--fix` binds the gate to the table that declares `f-Slicer` in the paired
model (never to whatever a stale binding names), repairing the first bound
filter (keeping its name; a bookmark gate's name is its `byName` key) only
when none is active, or appending one. The filter alias is always the letter
of `[gates] table` (`f`), whatever table declares the measure. A report whose
model declares no such table is left unchanged with a `REFUSED` line; the
other reports are still fixed and the exit code comes from the re-check.

## slicer-mode-gates

A dropdown slicer gates on `f-Slicer`, a vertical-list slicer on `f-All`
(`mode_map`); other modes are out of scope. The host table is the first table
of a sibling `*.SemanticModel` that declares both measures; without one the
run exits `2`.

- `GAT003`: the gate for the slicer's mode is absent or passive (visual or
  bookmark capture).
- `GAT004`: the gate is active but bound to a table that does not declare it.
- `GAT005`: a file holds gate references (a gate `Measure`, or the `From` of a
  filter that mentions a gate) that name another table.

`--fix` writes the gates and repoints stale references. In a stale filter's
`From` list only the alias a gate reference uses, or an entry naming the stale
table, is repointed; other sources are left alone. Both gate fixers write the
same shapes and name a new bookmark gate the same way, so running them in
either order gives identical files. Generated filter names are a stable hash,
so reruns agree.

## category-filter

`CAT001`: a bookmark listed in a `bookmarks.json` group (menu chrome such as
`Year`, `<`, `++`-prefixed or decorated labels skipped; all page-level
bookmarks when no group lists any) never filters
`[category.table][category.column]`, so applying it switches every gate off.

## theme

- `THM002` (error): no `themeCollection`.
- `THM003` (warning): no `customTheme`.
- `THM004` (error): `report.json` holds quoted hex colour literals, either
  a JSON string (`"#00FF00"`) or a DAX literal (`"'#FF0000'"`, how a
  hard-coded colour is saved); one finding with the count and up to 8
  samples.
- `THM005` (error): neither a base nor a custom theme.
- `THM006` (error): the base or the custom theme is missing (names which).

`--summary` counts and lists only `THM002`, `THM003` and `THM004` in the
theme row; `THM005` and `THM006` run under `--rule theme`.

## visual-position

`POS001` (error): a visual has no `position.x` or `position.y`.

## y-combo

- `YCG001`: a group named like a y-combo group does not match
  `y<N>_combo_group` exactly.
- `YCG002`: a `y<N>_*` member (at least one character after `y<N>_`) is not
  inside an existing `y<N>_combo_group`.

## filter-panel

Skipped when the report has no group containers.

- `PNL001`: no visual is named `panel.group_name` (the message reads `No
  y_filters_group master container found`).
- `PNL002` (warning): it exists but is not a group (the message reads
  `y_filters_group should be a group container, not specific visual`).

`--fix` acts only when the check reports `PNL001`: a report that already has
a visual named `panel.group_name` (whatever its folder is called) is left as
it is, with a `skipped` note. It works on the main page: the master is the
visible group object (display name not starting with `_`) that holds slicers
of at least two filter tables, most tables first, then the deepest, then the
smallest name; a visual that is not a group is never chosen. It is renamed,
child `parentGroupName` links and bookmark references follow, and the folder
is renamed last. The change line names the old name and display name and
the filter tables the group covers. Visual files it rewrites keep non-ASCII
text as `\u` escapes. An existing folder with the target name stops the fix
(exit 2).

## format-selector

Active only when the paired model has the `format_selector.table`.
`FMT001`: `report.json` does not hold exactly one filter on the format
selector column that selects `'Format'` and is hidden and locked in view mode
(the message names the first failing condition). The selected item is the
first non-empty literal across the filter's In rows. A report without
`definition/report.json` is skipped as not applicable; an unreadable one is
a finding. `--fix` replaces the
targeting filters with one canonical filter at the front, keeping the first
filter's name.

## stale-placeholders

Each dimension selector offers one blank-dimension placeholder column
(`NAMEOF('#Report Measures'[z])`). `PLH001`: a visual role or bookmark capture
bound to `y-*` selectors projects a placeholder those selectors do not offer
(bookmark captures also check their `byExpr` filters and `orderBy`; every
JSON file of the bookmarks folder holding exploration state is read, except
`bookmarks.json`). Roles
whose selectors offer several placeholders are skipped as ambiguous. `--fix`
sets the offered placeholder and updates `queryRef` / `nativeQueryRef`.

## answer-bookmarks

Answer bookmarks are the bookmarks whose display name starts with one of
`answer_bookmarks.prefixes` (required). Finding subjects start with the
bookmark's display name, so a baseline entry reads
`<file>::<display name>`.

| Id | Finding |
|---|---|
| `ABK000` | No bookmark matches the prefixes (the suite would check nothing) |
| `ABK001` | `options.targetVisualNames` is missing or not exactly `[]` |
| `ABK003` | The matrix is not captured, or captured as hidden |
| `ABK004` | Matrix rows differ from the row picker's picks, or the capture carries an inherited fingerprint |
| `ABK005` | The capture keeps `Values` in `activeProjections`, or expansion states |
| `ABK006` | A captured picker selects nothing |
| `ABK007` | The analysis category is not pinned with a literal |
| `ABK008` | The bookmark is not a child of a `Submenu` group |
| `ABK009` | The matrix slot map does not match the declared parameters or the picks |
| `ABK010` | A row field is missing from the dropdown filters |
| `PGW001` | A field-parameter well on the main page projects a raw measure |
| `PGW002` | A bookmark navigator on the main page selects a bookmark with no file |

Selections are read only from each slicer's saved filter, never from its
cached display items. Page and visual ids are discovered when not configured;
a main page or matrix that cannot be determined is a setup error (exit 2),
not a pass. So is a row parameter whose slicer cannot be determined (no
main-page slicer, or several, reference only that table): the error names
the candidates and the `[answer_bookmarks] slicers` key to set. A matrix with
no row parameter is noted under `skipped` (`ABK004`'s row comparison and
`ABK010` are not run). Overlapping parameter slots on any page are the
integrity rule's `FPM001` / `FPM002`. A bookmark file or main-page visual that
does not parse is a `JSN001` error, so the run fails instead of skipping it.
`ABK000` can never be accepted by a baseline: `--update-baseline` does not
write it, drops an entry for it, and exits 1 while it occurs. The text output
starts with `bookmarks tested: <n> | failures: <m>` (and, with no new finding,
`  all visual-level checks pass (ABK001, ABK003-ABK010, PGW001-PGW002)`);
`--json` has the count under `checked`. Findings are listed per bookmark in
check order (T1, T3, T4 rows, slot maps, inherited fields, capture shape,
pickers, dropdowns, category, submenu), then the page-level ones. Each run of
findings of one id is headed `<ID> — NEW finding(s), not in the baseline:`
and followed by a blank line and that id's guidance (also for `FPM001` /
`FPM002`). Messages start with the bare display name, for example
`<name>: Main Matrix captured as hidden`. `ABK006` names the picker by its
`[bookmarks] pickers` key when the config file has one. The slot check
compares the Rows and the Values slots by default (`slot_mode`).

Fix page-level findings (`PGW001`, `PGW002`) first: they reproduce in every
bookmark, so capture-level findings are only meaningful once the page is
right.

- `ABK000`: nothing matched, so every other check passed vacuously. Fix the
  `[answer_bookmarks] prefixes` setting (or the bookmark names).
- `ABK001`: a bookmark with a list in `targetVisualNames` applies only to
  those visuals, so its picker selections and filters are ignored; a missing
  key makes the menu entry unclickable. Re-capture the bookmark with no
  visual selected, or set the key to `[]` in the bookmark file.
- `ABK003`: the matrix is hidden on the page and shown only by each answer
  bookmark's capture. Re-capture with the matrix visible.
- `ABK004`: the matrix rows saved in the capture are what Power BI shows; rows
  that differ from the row picker, or a field inherited from the bookmark it
  was cloned from, show another question's answer. Rebuild the bookmark with
  `bookmarks build`.
- `ABK005`: active `Values` projections or expansion states pin the
  layout of the bookmark it was copied from. Rebuild it.
- `ABK006`: a picker captured with no selection leaves its visual empty.
  Every main-page selector slicer, row dropdown and configured slicer that a
  bookmark captures must select something. Pick a field and re-capture.
- `ABK007`: without a pinned analysis category the pickers offer every
  field. Set the category filter and re-capture.
- `ABK008`: only children of a `Submenu` group get a menu entry. Add the
  bookmark to a submenu group in `bookmarks.json`.
- `ABK009`: each parameter owns a slot range of the well; a pick outside its
  range renders nothing. The message names the picks outside their slots.
  Rebuild the bookmark.
- `ABK010`: each row field needs a dropdown filter so readers can narrow it.
  The message says what the dropdowns hold (or that they hold nothing).
  Mirror the rows into the dropdowns, or rebuild the bookmark.
- `PGW001`: a raw measure in a parameter well renders in every bookmark and
  no bookmark can remove it. Remove it from the page's `visual.json`.
- `PGW002`: the navigator's selected bookmark (a quoted 20-character
  lower-case hex id) has no bookmark file on disk. Point it at an existing
  bookmark.

## bookmark-literals

Each selector table registers the rows its `NAMEOF` tuples name (a bare
`[Measure]` resolves to the table declaring it). For each bookmark (or only
those named in `--only-display-names FILE.json`), every selection literal of
the active section is checked:

- `BML001`: a picker's literal is registered in another selector, not in the
  one behind this picker.
- `BML002`: the literal is registered in no selector.

`--only-display-names` takes a JSON list of names, or the `bookmarks build`
entries file (a list of objects with a `displayName`). The text output starts
with `bookmarks checked: <n> | literals OK: <ok> | UNREGISTERED: <bad>` (every
unresolved container literal counts; `--json`: `checked`). There is one finding
per (bookmark, literal, reason), sorted: `<display name>  ->  <'table'[field]>`
and, on the next line, the reason. Without a usable paired model the rule cannot judge a report:
when no report of the run was judged it is a setup error (exit 2) naming
`--model`; otherwise the report is listed under `skipped`. An unreadable
bookmark file is a `JSN001` error.

## --summary

`check --summary` runs `slicer-gates`, `category-filter`, `theme` and
`filter-panel` and reports per rule how many components were checked and
passed (failures among its critical ids) and whether it is compliant (no
error finding at all), plus
the overall percentage. It never fails; `--json` adds a `compliance` object.
The finding lines, the closing `Checked` totals and the `--json` `findings`
and `summary` carry only the ids the rows count, so they agree with the
score.
Each finding is followed by a one-line remediation hint (`fix:`; a `fix`
field on each finding in `--json`).

## Baselines

`--baseline FILE` accepts the findings it lists; only others fail the run.
Accepted entries of this run's rules and reports that no longer occur are
listed once per id: `<ID>: <n> accepted finding(s) no longer occur —
re-capture the baseline (pbi-plot-styler check --update-baseline) to lock it
in: [<locations>]`; entries of other rules or reports are never called healed.

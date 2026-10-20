# Commands beyond style and check

`check --fix` runs the fixers and then checks again from disk: its exit code
comes from that re-check (`0` clean, `1` findings left), so a fix that could
not repair everything still fails the run. `check` over a folder that holds
no `*.Report` folder prints that there is nothing to check and exits `0`; a
`--report` or `--model-name` filter that matches nothing exits `2`. Reports
are found at any depth.

## colors sync / colors reset

```bash
pbi-plot-styler colors sync --report "Shop.Report" [--model "Shop.SemanticModel"] [--apply]
pbi-plot-styler colors reset --report "Shop.Report" [--apply]
```

The colour rule lives in the model as a palette measure (default
`'w-Colors'[c-Measure Color]`, `--measure`, `--palette-table`) of the form:

```dax
VAR _order = SELECTEDVALUE ( 'x-Selector 1'[x-Selector 1 Order] )
VAR _slot = MOD ( _order + 0, 3 ) + 1
RETURN SWITCH ( _slot, 1, "#111111", 2, "#222222", 3, "#333333" )
```

A measure's colour is the slot its row's sort order lands on in the picker
field parameter named by `SELECTEDVALUE`. The palette must declare exactly
`modulus` slots.

`sync` (a dry run unless `--apply`) first prints the palette (picker,
offset, modulus, slot count) and the number of registered measures, then
stamps:

- column series (bar, column, line and combo charts, including plain
  `barChart` and `columnChart`): `dataPoint` fill for the measures on the
  `Y` role plus the measures a multi-series bookmark shows on that visual (a
  capture with at least `--min-series` measures on `Y`). Line (`Y2`) entries
  of the visual are never touched.
- matrices bound to the picker (the picker is a field parameter of a value
  role): `columnFormatting` font colour plus `styleValues`, `styleHeader` and
  `styleTotal` for the registered measures the matrix projects as measure
  fields (the field-parameter column itself adds none); registered measures
  that are not needed get black. A matrix in scope only through
  `--all-visuals` uses the bookmark-needed measures.
- bookmark overrides under `objects.merge` (or directly under `objects`),
  matched on page section and visual id, only where the array already
  exists: existing entries are recoloured and every needed measure the array
  lacks is added (sorted by key). A chart override's needed set keeps the
  base visual's line measures.

A visual uses the picker only through a value role (columns, line or values);
`--visual-type` is applied first, silently. Colours are written exactly as
the palette spells them. `--all-visuals` stamps every supported visual. Each
multi-series bookmark's series are listed with role, sort order and colour;
unregistered series (line series included) and colour collisions are
reported as notes, with a re-spacing hint. The run ends with the number of
entries rewritten and added.

`reset` reverts entries of the picker's registered measures whose colour is a
palette colour (or black, compared case-insensitively), on visuals and on
bookmark overrides: chart fills go back to theme colour `--default-color-id`
(9); matrix entries lose the font colour and any style flag that is `true`,
and disappear when empty (an empty array is removed). `--visual-type`
(repeatable) limits both visuals and bookmark captures.

Exit codes: `0` changes written, or nothing to change; `1` a dry run found
changes to make (rerun with `--apply`); `2` invalid input (palette or picker unreadable, an unresolvable bare `NAMEOF`,
no registered measure). Invalid input writes nothing.

## bookmarks build

```bash
pbi-plot-styler bookmarks build entries.json --report "Newsletter.Report" \
    --config plotstyler.toml --base <bookmark name> --group <group name>
```

`entries.json` is a list; each entry produces one bookmark from a deep copy of
the base bookmark, with a fresh 20-hex-character name. Entry keys:

| Key | Effect |
|---|---|
| `displayName` | Required |
| `base` | Base bookmark for this entry (beats `--base` and `[bookmarks] base`; in re-render mode an existing bookmark with the display name still wins) |
| `pickers` | `{picker key: [{table, column, label}, ...]}`: the slicer's saved selection and cached labels |
| `show`, `hide` | Visual ids to show (removes `display`) or hide |
| `show_groups`, `hide_groups` | Visual group ids to show or hide |
| `target_visuals` | `options.targetVisualNames` (default `[]`; the key is never removed) |
| `analysis_category` | One value or a list for the category filter (`null` or empty: unchanged) |
| `date_filter` | `this_year`: the relative-date filter selects the current year (`null`: unchanged; any other value is an error) |
| `drill_level` | The chart's Category hierarchy level (`null` or empty: unchanged) |
| `unhide_matrix` | `false` keeps the base matrix capture |
| `matrix_sort` | `{measure: {table, column}}` or `{column: {...}}`, or the flat `{table, column, kind}` (`kind` `measure` by default); optional `direction` (default 2; `1`/`2`, `"1"`, `ascending`/`descending`) |
| `group` | bookmarks.json group for this entry (beats `--group`) |
| `clear_filters` | `byExpr` filters whose `filter` is dropped (report and page level) |

Settings live in the `[bookmarks]` section: `base`, `matrix`, `chart`,
`row_picker`, `row_dropdowns`, `category_column`, `calendar_table`
(default `__Calendar`), `calendar_hierarchy` (default `Calendar Hierarchy`),
`pickers = {key = "<slicer visual id>"}` and
`wells = {matrix_rows, matrix_values, chart_y, chart_y2, chart_series}`
(lists of picker keys). The well map has no built-in default: list the
pickers that feed each well. Other keys in an entry are ignored.

The builder gives every row pick a row dropdown (more picks than dropdowns
is an error; a dropdown the entry sets itself is kept, and a free dropdown
that receives no row keeps the base bookmark's pick, so no captured dropdown
selects nothing). The matrix Rows and Values wells and their slot map are
built from the entry's own picks plus the mirrored rows only: a picker the
entry does not mention keeps its saved selection on its slicer but adds
nothing to any well. Each picker of a well with projections gets a slot at
the running index (length 0 when it has no picks); a slot names the
field parameter's display column (the column named like the parameter's
table), never the hidden fields column the picker filters on. A pick may
appear only once per well (matrix and chart). A chart well is rebuilt, and
its slot map replaced, only when the entry mentions one of its pickers. A
picker named with an empty list keeps its In condition with no values and an
empty cached list. Bookmark files are written as UTF-8 with non-ASCII text
as is. The date filter's calendar alias is the calendar table's first
character (`_` for `__Calendar`).

`--keep-ids` re-renders: a bookmark with the entry's display name is the base
and keeps its name and its place in `bookmarks.json`; only new bookmarks are
registered, at the front of the group. Two existing bookmarks with the same
display name are an error naming both. Each written line says whether the id
was kept or new and shows the display name.

`--legacy-layout` renders the single-page layout: the `x_selector_1` picker
(`legacy_measures`) fills the matrix values (at least 3) and the row picker 1
to 3 rows. Rows are not mirrored: every other picker holds exactly the picks
the entry gives it, or is emptied (conditions removed, cached list kept
empty). The matrix capture is edited in place: only the Rows and Values
projections, their slots (length and index updated, other slot keys kept),
the first sort entry (pointed at the first measure, keeping its direction
and later entries; a single descending entry is added only when there is
none), the active rows (all of them) and the first container-level
expression filter (pointed at the first measure) change; the display mode,
expansion states, prototype query and other roles stay as the base had them.
A matrix the base captures only under a stale id (exactly one matrix-shaped
capture whose id is no visual on the page) is moved to the configured id,
with a note. Without `target_visuals` the bookmark is scoped to the matrix.
The category filter is looked up in the page's `byExpr` list and `byName`
map; a base without one is left as it is. Values slicers are `pickers` keys
named `y_values_slicer_<N>` (N = 2..6), each listing the values of the
dimension picked in `y_selector_<N>`: the layout always clears their
preselection and, when the entry gives `y_selector_<N>` picks, points their
column at its first pick (never a measure). They cannot be picked in an
entry, and one the base bookmark does not capture is skipped.

Output: one line per written bookmark, its absolute file path, in entry
order and nothing else. With `--keep-ids` each line is `kept <id> <display
name>` or `NEW  <id> <display name>` instead. Notes (such as a moved matrix
capture) go to stderr. Error messages start with the entry's display name
(`<display name>: base bookmark does not capture the Main Matrix`), except the
legacy-layout limits, which start with the entry's analysis category
(`Spend: need >=3 measures, got 2`). `--self-test` builds one synthetic entry
from the base bookmark in memory, checks it and prints `self-test PASS`
(the legacy layout adds the generated name, the measures and the matrix row
count); nothing is written.

The default layout always leaves a `visualContainerGroups` map on the built
section and `projections` / `parameters` on a captured chart; the legacy
layout always leaves an emptied picker with an empty cached list.

`--dry-run` builds everything and writes nothing. Any invalid entry,
missing picker, chart or matrix capture, filter or base stops the run with
exit `2` before a file is written.

## rename-measure

```bash
pbi-plot-styler rename-measure "CPA" "Cost/ Conversion" --model client/Growth.SemanticModel [--dry-run]
```

Renames a measure in every `visual.json` and `*.bookmark.json` of every
`*.Report` folder under the model's parent folder, at any depth. Rewritten
(case-insensitive): `Measure` bindings, `queryRef` / `metadata` strings ending
in the name, `nativeQueryRef`, and each `[name]` inside saved selection
literals. Labels follow only while they still equal the old label
(`--label-from` / `--label-to`) and a sibling binds the measure: cached
display items, projection labels and value maps. `Column` bindings are never
touched, and neither are the references or label of a column projection that
shares the measure's name. Names with `'` or `]` are matched and written in
their escaped literal form, and each file keeps its BOM and line endings. The dry-run count equals the number of rewrites. The model side
(declaration, DAX) is not edited. The same functions are importable from
`pbi_plot_styler.rename` (`report_roots`, `count_tree`, `rewrite_tree`,
`count_measure_refs`, `rename_measure`).

## rename-label

```bash
pbi-plot-styler rename-label client/ --pair "Cost/ New Customer" "CAC" [--pair OLD NEW ...] [--apply]
```

Replaces the quoted label (`"OLD"`, never the bare text) in the `x-*` selector
tables (`--table-pattern`) of every model directly under the folder and in the
visuals, pages and bookmarks of every report below it. With several pairs the
longest old label goes first. A JSON file that would no longer parse stops
the run with nothing written: the rename is all or nothing. Prints one line
per pair, the count first (right-aligned) and then the quoted pair, then
`DRY RUN` or `APPLIED` with the touched files in visiting order (model tables
first, then reports). Paths are relative to the client folder and always use
`/`, on Windows too.

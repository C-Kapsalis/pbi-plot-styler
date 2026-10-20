# Commands beyond style and check

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

`sync` (a dry run unless `--apply`) stamps:

- column series (bar, line and combo charts): `dataPoint` fill for the
  measures on the `Y` role plus the measures a multi-series bookmark shows on
  that visual (a capture with at least `--min-series` measures on `Y`). Line
  (`Y2`) entries are never touched.
- matrices bound to the picker: `columnFormatting` font colour plus
  `styleValues`, `styleHeader` and `styleTotal`; registered measures that are
  not needed get black.
- bookmark overrides under `objects.merge`, only where they already exist.

Colours are written as literal `'#rrggbb'` values. `--all-visuals` stamps
every supported visual. Unsupported visuals bound to the picker, unregistered
bookmark measures and colour collisions are reported as notes.

`reset` reverts entries whose colour is a palette colour (or black): chart
fills go back to theme colour `--default-color-id` (9); matrix entries lose
the owned properties and disappear when empty.

Exit codes: `0` changes (planned or written), `2` nothing to change, `3`
invalid input (palette or picker unreadable, an unresolvable bare `NAMEOF`,
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
| `pickers` | `{picker key: [{table, column, label}, ...]}`: the slicer's saved selection and cached labels |
| `show`, `hide` | Visual ids to show (removes `display`) or hide |
| `show_groups`, `hide_groups` | Visual group ids to show or hide |
| `target_visuals` | `options.targetVisualNames` (default `[]`; the key is never removed) |
| `analysis_category` | One value or a list for the category filter |
| `date_filter` | `this_year`: the relative-date filter selects the current year |
| `drill_level` | The chart's Category hierarchy level |
| `unhide_matrix` | `false` keeps the base matrix capture |
| `matrix_sort` | `{measure: {table, column}}` or `{column: {...}}`, optional `direction` (default 2) |
| `group` | bookmarks.json group for this entry (beats `--group`) |
| `clear_filters` | With `--keep-ids`: `byExpr` filters whose `filter` is dropped |

Settings live in the `[bookmarks]` section: `base`, `matrix`, `chart`,
`row_picker`, `row_dropdowns`, `category_column`, `calendar_table`,
`calendar_hierarchy`, `pickers = {key = "<slicer visual id>"}` and
`wells = {matrix_rows, matrix_values, chart_y, chart_y2, chart_series}`
(lists of picker keys). The well map has no built-in default: list the
pickers that feed each well.

The builder mirrors the row picker's picks into the row dropdowns when the
entry fills none of them (more picks than dropdowns is an error); rebuilds the
matrix Rows and Values wells and their slot map (a pick may appear only once
per well); rebuilds a chart well only when the entry mentions one of its
pickers; and writes each picker's selection literal `'''table''[column]'`.
A picker the entry does not mention keeps the base selection, which also
feeds the matrix wells.

`--keep-ids` re-renders: a bookmark with the entry's display name is the base
and keeps its name, and new bookmarks go to the front of the group.
`--legacy-layout` renders the single-page layout: the `x_selector_1` picker
(`legacy_measures`) fills the matrix values (at least 3), the row picker 1 to
3 rows, the matrix sorts on the first measure, and unmentioned pickers are
emptied. `--dry-run` builds everything and writes nothing. Any invalid entry,
missing picker, filter or capture stops the run with exit `2` before a file
is written.

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
the run with nothing written. Prints one count line per pair, then `DRY RUN`
or `APPLIED` with the touched files.

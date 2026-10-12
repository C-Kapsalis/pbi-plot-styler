# pbi-plot-styler

**A reporting template for Power BI that scales by declaration, and the CLI
that keeps it presentation-ready.**

## The template: one page, three field parameters

Most Power BI reports grow one page at a time. A new metric arrives, someone
copies a page, swaps the measure, re-formats the visuals by hand. Twenty
metrics later you maintain twenty near-identical pages, no two formatted
alike, and every style decision has to be re-made twenty times.

There is a better shape for recurring, metric-by-metric performance
reporting: **one page, driven by three field parameters** declared in the
semantic model. `BI-report-template-site` is where that pattern is taught
end to end, as a live, clickable demo aimed at a reader with no data team;
this tool is what keeps a report that follows it presentation-ready as
measures are added. The three parameter tables:

| Table | Role in the chart | Contents |
|---|---|---|
| `x-Plot Specific 1` | Axis | Every dimension a chart can be sliced by, time grains first, then entity attributes (`Month`, `Quarter`, `Origin Country`, …) |
| `x-Plot Specific 2` | Legend | Every dimension a chart can be split into series (`Channel`, `Brew Method`, …) |
| `y-Plot Specific` | Values | Every measure a chart can display (`Revenue`, `Bags Sold #`, …) |

Bind one line-and-clustered-column combo chart to the three parameters, put
the numbers beside it in a matrix bound to the same fields, add one slicer
per parameter, and that canvas becomes your whole reporting surface. Viewers
compose the chart they need at view time; a **bookmark** captures any
composition worth naming. "Revenue by month by channel" stops being a page
you maintain and becomes a saved slicer state that costs nothing to keep.

The economics invert:

- **Every measure anyone adds inherits the page.** Adding the twenty-first
  metric costs the same as the first: one tuple in a TMDL file.
- **No per-visual hand-formatting.** Content lives in the model; the page is
  a generic lens over it.
- **Plots are always presentation-ready.** Same colors, same labels, same
  backgrounds, screenshot any composition straight into a deck.
- **The plottable surface is reviewable.** The parameter tables are readable
  DAX in version control; adding a measure is a one-line diff.

Declaring a parameter is ordinary TMDL, a calculated table of
`( display name, NAMEOF ( field ), sort ordinal, category )` tuples
(adapted from [the test fixture](tests/fixtures/roastery/Roastery.SemanticModel/definition/tables/y-Plot%20Specific.tmdl)):

```
	partition 'y-Plot Specific' = calculated
		mode: import
		source =
				{
				    ( "Bags Sold #", NAMEOF ( [Bags Sold #] ), 10, "sales_y" ),
				    ( "Revenue", NAMEOF ( 'Sales Measures'[Revenue] ), 20, "sales_y" ),
				    ( "Avg Cupping Score", NAMEOF ( [Avg Cupping Score] ), 30, "quality_y" ),

				    -- retired measures stay parked here, commented out
				    -- ( "Retired Blend Sales", NAMEOF ( [Retired Blend Sales] ), 50, "sales_y" ),
				    ( "Sample Requests #", NAMEOF ( [Sample Requests #] ), 70, "sales_y" )
				}
```

`NAMEOF` makes the rows references, not strings, so renaming a measure
updates the parameter automatically. Space the ordinals so you can insert
without renumbering; comment out retirements instead of deleting them. The
full table declaration (three columns plus this partition) is in the
[documentation](#documentation) below.

## The catch, and the CLI

One thing field parameters cannot reach: **per-measure formatting**. Power BI
stores series colors and data-label backgrounds as selector arrays inside
each visual's `visual.json`, keyed by measure name. Those arrays do not
follow the model. Add a measure and it plots unstyled, its labels unreadable
over the columns. Rename one and a dead entry stays behind. Hand-formatting
is discipline; `pbi-plot-styler` is a guarantee.

The CLI reads the measures your field-parameter tables declare and, for
every `lineClusteredColumnComboChart` in the report, writes one entry per
measure into two arrays under `visual.objects`:

- **`dataPoint[]`**: the series fill (line and columns alike), selected via
  `selector.metadata = "<Table>.<Measure>"`, as a hex color or a theme color.
- **`labels[]`**: the data-label `backgroundColor` and
  `backgroundTransparency` of each measure, plus a no-selector entry with
  `enableBackground: true` (without which Power BI ignores every
  per-measure background), seeded with data labels on and your text color
  when the visual has no label settings yet.

The styler owns those per-measure entries and nothing else. Formatting you
set by hand survives every run: the column baseline (the no-selector
`dataPoint` entry), per-legend-value entries (`selector.data`), the entries
of measures drawn as columns, and any extra property next to the ones the
tool sets. The operation is **deterministic** (same model + config =
byte-identical output), **idempotent** (re-running a styled report is a
no-op that touches no bytes), and **self-healing** (entries for renamed or
retired measures are dropped). Here is a trimmed real diff from
`--dry-run` on the bundled fixture, whose `combo01` visual carries a stale
hand-formatted entry for a retired measure:

```diff
--- definition/pages/monthlyperformance/visuals/combo01/visual.json
+++ definition/pages/monthlyperformance/visuals/combo01/visual.json (styled)
@@ -159,19 +159,246 @@
                 "color": {
                   "expr": {
                     "Literal": {
-                      "Value": "'#A0522D'"
+                      "Value": "'#118DFF'"
 ...
           "selector": {
-            "metadata": "Sales Measures.Retired Blend Sales"
+            "metadata": "Quality Measures.Avg Cupping Score"
           }
         },
+        ... one dataPoint entry per declared measure ...
       ],
-      "labels": []
+      "labels": [
+        ... show / text color / enableBackground, then per measure: ...
+        {
+          "properties": {
+            "backgroundColor": { "solid": { "color": { "expr": { "Literal": { "Value": "'#118DFF'" } } } } },
+            "backgroundTransparency": { "expr": { "Literal": { "Value": "20L" } } }
+          },
+          "selector": { "metadata": "Sales Measures.Revenue" }
+        },
 ...
```

The dead `Retired Blend Sales` entry (commented out in the parameter table)
is gone; every live measure gets a fill and a label background. Everything
else in the file (queries, position, other `objects`, hand-made formatting
entries) is preserved verbatim, and so are the file's line endings and
end-of-file convention.

## Install

```bash
pip install .
```

Python 3.10+. Runtime dependencies: `click` (plus `tomli` on 3.10).

## Quickstart

Point it at the report folder of a PBIP project; the paired semantic model is
resolved from `definition.pbir` automatically:

```bash
pbi-plot-styler "Roastery.Report"
```

```
Model:    .../Roastery.SemanticModel
Measures: 5 drive the styling
  styled definition/pages/monthlyperformance/visuals/combo01/visual.json
  styled definition/pages/seasonaltrends/visuals/combo02/visual.json

Restyled 2/2 visual(s); 0 already styled.
```

Run it again and it reports `Restyled 0/2 visual(s); 2 already styled`, the
command is safe to run after every model change, mechanically.

`REPORT_DIR` can also be any folder that contains one or more `*.Report`
folders, at any depth: every report found is styled against its own model.

```bash
pbi-plot-styler path/to/workspace --dry-run
```

If your report folder's name begins with a dash, prefix it with `./` (or end
option parsing with `--`) so it is not read as a flag:

```bash
pbi-plot-styler "./-Sales.Report"
```

## Try it on the bundled example

[`examples/coffee-roastery/`](examples/coffee-roastery/) is a complete,
openable PBIP project (fictional, inline data, refreshes offline with no data
source) shipped **deliberately unstyled**, so you can watch the styler change
it. Preview the rewrite without touching anything:

```bash
# bash / macOS / Linux
pbi-plot-styler examples/coffee-roastery/Roastery.Report --dry-run
```

```powershell
# PowerShell / Windows
pbi-plot-styler examples\coffee-roastery\Roastery.Report --dry-run
```

To *see* the before and after in Power BI Desktop: open the unstyled charts,
run the styler on a copy, then reopen the styled charts. The walkthrough for
that is in [the example's README](examples/coffee-roastery/README.md). The
styler itself runs anywhere Python does; only the "open the `.pbip` to look
at it" step needs Windows with Power BI Desktop.

## Configuration

Every knob is a CLI flag and a `plotstyler.toml` key (auto-loaded from the
working directory, or passed via `--config`). Precedence: **CLI flags >
config file > defaults.** All hex colors are 6-digit `#RRGGBB`.

| TOML key | CLI flag | Default | Controls |
|---|---|---|---|
| `tables.field_parameters` | `--table` (repeatable) | `x-Plot Specific 1`, `x-Plot Specific 2`, `y-Plot Specific` | Field-parameter tables whose `NAMEOF` measure references drive the styling. Restrict this to just the table that feeds your line to style only the line; if that table's measure catalog overlaps with the columns' table, also set `exclude_current_roles` below. |
| `tables.renames` | `--rename-table OLD=NEW` (repeatable) | none | Renames one table in the list above, leaving the other default names in place |
| `targets.visual_types` | `--visual-type` (repeatable) | `lineClusteredColumnComboChart`, `lineStackedColumnComboChart` | Which `visualType` values get restyled |
| `targets.exclude_current_roles` | `--exclude-role NAME` (repeatable) | none | Query role (for example `Y`, Power BI's internal name for the columns) whose measures are excluded from styling, per visual: the measure bound to it, or, when the role is bound through a field parameter, every measure that parameter offers. Their existing formatting is kept. Re-reads the binding on every run. |
| `style.line_color` | `--line-color` | `#118DFF` | Series fill (line and columns) for every measure |
| `style.palette` | `--palette` (repeatable) | empty | Colors assigned per measure by its stable slot (the field parameter's sort order, first registration wins); overrides `line_color` and `theme_color_id` when set |
| `style.colors` | `--color "TABLE.MEASURE=HEX"` (repeatable) | none | Pins one measure's color; beats the palette, theme color, and line color. A pin matching no measure is an error |
| `style.theme_color_id` | `--theme-color-id N` | not set | Uses theme data color `N` (a `ThemeDataColor`) instead of `line_color`, so the chart follows theme changes |
| `style.theme_color_percent` | `--theme-color-percent P` | `0` | Lightens (0 to 1) or darkens (-1 to 0) the theme color |
| `style.label_color` | `--label-color` | `#252423` | Data-label text color |
| `style.label_background` | `--label-background` | match line color | Data-label background per measure |
| `style.label_transparency` | `--label-transparency` | `20` | Background transparency, 0 to 100. Seeded where a measure has none; enforced everywhere when set explicitly |
| `style.show_labels` | `--show-labels` / `--hide-labels` | `true` | Data labels on/off. Seeded on visuals without label settings; enforced when set explicitly (likewise `label_color`) |
| - | `--model DIR` | from `definition.pbir` | Semantic-model folder override |
| - | `--config FILE` | `./plotstyler.toml` if present | Config file path |
| - | `--dry-run` | off | Diff only; write nothing |
| - | `--zip OUT.zip` | - | Also emit the styled report as an archive |

A brand-color config looks like:

```toml
[style]
line_color = "#7A4419"
label_color = "#FFF8F0"
label_transparency = 30

[style.colors]
"Sales Measures.Revenue" = "#2E7D32"
```

## Dry-run and CI

`--dry-run` prints a unified diff per out-of-style visual and writes nothing.
Exit codes are CI-grade:

| Code | Meaning |
|---|---|
| `0` | Nothing to change, report matches the model and config |
| `1` | Drift: at least one visual would change (`--dry-run` only) |
| `2` | Error: bad config value, missing folder, unresolvable model, no measures, no report or no targeted visual found |

So `pbi-plot-styler "My Project.Report" --dry-run` in a pipeline turns your
style guide into a gate: a PR that adds a measure without re-running the
styler fails until someone runs the one command.

## Check mode

`pbi-plot-styler check PATH` is a read-only integrity gate for one report or
a folder of reports. It catches the breakages Power BI only reveals at
import or render time:

| Id | Severity | Finding |
|---|---|---|
| `JSN001` | error | A report file is not valid JSON |
| `BND001` | error | A field reference (table plus measure, column, or hierarchy level, including filters' `From` aliases) does not resolve in the paired model |
| `BND002` | error | A `queryRef` or `selector.metadata` string does not resolve |
| `BMK001` | error | A bookmark `options` key is outside the allowed set (fixable) |
| `BMK002` | error | A bookmark `howCreated`, `ComparisonKind` or `Version` is a string, not an integer (fixable when numeric) |
| `BMK003` | error | A bookmark names a page that does not exist |
| `BMK004` | error | A bookmark captures a visual that is not on that page |
| `BMK005` | error | `bookmarks.json` lists a bookmark with no file |
| `FPM001` | error | Two field parameters of one role claim the same slot |
| `FPM002` | error | A field parameter's slots run past the role's projections |
| `THM001` | warning | A `themeCollection` entry does not resolve to a theme file |

```bash
pbi-plot-styler check "My Project.Report"            # text report
pbi-plot-styler check "My Project.Report" --json     # machine-readable
pbi-plot-styler check "My Project.Report" --fix      # repair BMK001/BMK002
```

Exit codes: `0` no new errors (warnings never fail), `1` new errors, `2`
setup problem. `--fix` edits text surgically and verifies by parsing both
sides that only the intended change happened; otherwise it refuses and
leaves the file untouched. To adopt the gate on a report with known
findings, record them once with `--baseline check-baseline.json
--update-baseline`, then run with `--baseline check-baseline.json`: only new
findings fail, and fixed ones are reported as healed. A report whose model
is not a local folder still gets every check except the binding checks.

Run the check after a measure rename or a bookmark change; run the styler
after a field-parameter change.

## Zip output

`--zip styled-report.zip` additionally writes the styled report folder as an
archive (rooted at the folder name), a shippable snapshot for whoever
publishes. Combined with `--dry-run`, the archive contains the *styled*
content while the source files stay untouched: a preview build.

## Documentation

The full documentation (a tutorial that declares the three field parameters
and styles a combo-chart page end to end, a CLI reference covering every
argument, option, config key, and exit code, and an explanation of why the
template beats per-visual hand-formatting) is published on Read the Docs at
<https://pbi-plot-styler-documentation.readthedocs.io/en/latest/>.

## Part of a small family of Power BI tools

pbi-plot-styler is one of a few related, independently installable tools; a
team adopts whichever ones it needs, not all of them.

- [`tmdl-preflight`](https://github.com/C-Kapsalis/tmdl-preflight): a linter
  and auto-fixer for a single TMDL-format model.
- [`tmdl-drift-doctor`](https://github.com/C-Kapsalis/tmdl-drift-doctor):
  keeps many derived models in sync with one shared template.
- [`pbip-model-forge`](https://github.com/C-Kapsalis/pbip-model-forge):
  builds a sample Power BI model from a plain-language description.
- [`BI-report-template-site`](https://github.com/C-Kapsalis/BI-report-template-site):
  not a tool, the live demo and documentation that teaches the one-canvas,
  field-parameter reporting pattern this CLI keeps styled.

## Contributing

Contributions are welcome: new config keys, bug fixes, and documentation.
See [CONTRIBUTING.md](CONTRIBUTING.md) for the development setup.

## License

MIT © 2026 Christoforos Kapsalis

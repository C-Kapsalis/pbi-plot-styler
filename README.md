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
semantic model:

| Table | Role in the chart | Contents |
|---|---|---|
| `x-Plot Specific 1` | Axis | Every dimension a chart can be sliced by — time grains first, then entity attributes (`Month`, `Quarter`, `Origin Country`, …) |
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
  backgrounds — screenshot any composition straight into a deck.
- **The plottable surface is reviewable.** The parameter tables are readable
  DAX in version control; adding a measure is a one-line diff.

Declaring a parameter is ordinary TMDL — a calculated table of
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

`NAMEOF` makes the rows references, not strings — rename a measure and the
parameter follows. Space the ordinals so you can insert without renumbering;
comment out retirements instead of deleting them. The full table declaration
(three columns plus this partition) is in the
[getting-started tutorial](docs/tutorials/getting-started.md).

## The catch — and the CLI

One thing field parameters cannot reach: **per-measure formatting**. Power BI
stores series colors and data-label backgrounds as selector arrays inside
each visual's `visual.json`, keyed by measure name. Those arrays do not
follow the model. Add a measure and it plots unstyled, its labels unreadable
over the columns. Rename one and a dead entry stays behind. Hand-formatting
is discipline; `pbi-plot-styler` is a guarantee.

The CLI reads the measures your field-parameter tables declare and rebuilds,
for every `lineClusteredColumnComboChart` in the report, exactly two arrays
under `visual.objects`:

- **`dataPoint[]`** — one entry per measure, binding the series fill (line
  and columns alike) to your hex color via
  `selector.metadata = "<Table>.<Measure>"`.
- **`labels[]`** — a leading entry that switches data labels on, sets the
  text color, and sets `enableBackground: true` (without which Power BI
  ignores every per-measure background), then one entry per measure with its
  `backgroundColor` and `backgroundTransparency`.

Both arrays are regenerated from scratch off the sorted measure list, so the
operation is **deterministic** (same model + config = byte-identical output),
**idempotent** (re-running a styled report is a no-op), and **self-healing**
(stale entries are discarded wholesale). Here is a trimmed real diff from
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
else in the file — queries, position, other `objects` — is preserved
verbatim.

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

Run it again and it reports `Restyled 0/2 visual(s); 2 already styled` — the
command is safe to run after every model change, mechanically.

If your report folder's name begins with a dash, prefix it with `./` (or end
option parsing with `--`) so it is not read as a flag:

```bash
pbi-plot-styler "./-Sales.Report"
```

## Configuration

Every knob is a CLI flag and a `plotstyler.toml` key (auto-loaded from the
working directory, or passed via `--config`). Precedence: **CLI flags >
config file > defaults.** All hex colors are 6-digit `#RRGGBB`.

| TOML key | CLI flag | Default | Controls |
|---|---|---|---|
| `tables.field_parameters` | `--table` (repeatable) | `x-Plot Specific 1`, `x-Plot Specific 2`, `y-Plot Specific` | Field-parameter tables whose `NAMEOF` measure references drive the styling |
| `targets.visual_types` | `--visual-type` (repeatable) | `lineClusteredColumnComboChart` | Which `visualType` values get restyled |
| `style.line_color` | `--line-color` | `#118DFF` | Series fill (line and columns) for every measure |
| `style.palette` | `--palette` (repeatable) | empty | Colors cycled per measure (sorted order); overrides `line_color` when set |
| `style.label_color` | `--label-color` | `#252423` | Data-label text color |
| `style.label_background` | `--label-background` | match line color | Data-label background per measure |
| `style.label_transparency` | `--label-transparency` | `20` | Background transparency, 0–100 |
| `style.show_labels` | `--show-labels` / `--hide-labels` | `true` | Data labels on/off |
| — | `--model DIR` | from `definition.pbir` | Semantic-model folder override |
| — | `--config FILE` | `./plotstyler.toml` if present | Config file path |
| — | `--dry-run` | off | Diff only; write nothing |
| — | `--zip OUT.zip` | — | Also emit the styled report as an archive |

A brand-color config looks like:

```toml
[style]
line_color = "#7A4419"
label_color = "#FFF8F0"
label_transparency = 30
```

## Dry-run and CI

`--dry-run` prints a unified diff per out-of-style visual and writes nothing.
Exit codes are CI-grade:

| Code | Meaning |
|---|---|
| `0` | Nothing to change — report matches the model and config |
| `1` | Drift: at least one visual would change (`--dry-run` only) |
| `2` | Error: bad config value, missing folder, unresolvable model, no measures |

So `pbi-plot-styler "My Project.Report" --dry-run` in a pipeline turns your
style guide into a gate: a PR that adds a measure without re-running the
styler fails until someone runs the one command.

## Zip output

`--zip styled-report.zip` additionally writes the styled report folder as an
archive (rooted at the folder name) — a shippable snapshot for whoever
publishes. Combined with `--dry-run`, the archive contains the *styled*
content while the source files stay untouched: a preview build.

## Documentation

- [Getting started](docs/tutorials/getting-started.md) — declare the three
  field parameters, build the combo-chart page, style it end to end.
- [CLI reference](docs/reference/cli.md) — every argument, option, config
  key, rewrite rule, and exit code.
- [Field-parameter reporting](docs/explanation/field-parameter-reporting.md)
  — why the template beats per-visual hand-formatting, the trade-offs, and a
  combo-chart quirk worth knowing before you bind the same measure to both
  axes.

## License

MIT © 2026 Christoforos Kapsalis

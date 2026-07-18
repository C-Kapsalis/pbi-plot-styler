# Getting started

In this tutorial you will set up the field-parameter reporting pattern in a
Power BI (PBIP) project and use `pbi-plot-styler` to make its combo charts
presentation-ready. By the end you will have:

1. three field-parameter tables in your semantic model,
2. a combo-chart page driven by them, and
3. every chart styled by one command — and re-styled by the same command
   whenever the model changes.

The worked example is a small specialty-coffee roastery. Substitute your own
tables and measures as you go.

## Prerequisites

- A Power BI project saved in **PBIP format** (a `*.Report` folder next to a
  `*.SemanticModel` folder, with TMDL enabled).
- Power BI Desktop (any recent version with field-parameter support).
- Python 3.10+ with `pbi-plot-styler` installed:

  ```bash
  pip install .
  ```

## Step 1 — Declare the measures: `y-Plot Specific`

A field parameter is a calculated table whose rows say "this field may appear
in this well". Create one named `y-Plot Specific` listing every measure a
combo chart should be able to display. In Power BI Desktop, use *Modeling →
New parameter → Fields*, or add the TMDL directly to
`definition/tables/y-Plot Specific.tmdl`:

```
table 'y-Plot Specific'

	column 'y-Plot Specific'
		summarizeBy: none
		sourceColumn: [Value1]
		sortByColumn: 'y-Plot Specific Order'

		relatedColumnDetails
			groupByColumn: 'y-Plot Specific Fields'

	column 'y-Plot Specific Fields'
		isHidden
		summarizeBy: none
		sourceColumn: [Value2]
		sortByColumn: 'y-Plot Specific Order'

		extendedProperty ParameterMetadata =
				{
				  "version": 3,
				  "kind": 2
				}

	column 'y-Plot Specific Order'
		isHidden
		formatString: 0
		summarizeBy: sum
		sourceColumn: [Value3]

	partition 'y-Plot Specific' = calculated
		mode: import
		source =
				{
				    ( "Bags Sold #", NAMEOF ( [Bags Sold #] ), 10, "sales_y" ),
				    ( "Revenue", NAMEOF ( 'Sales Measures'[Revenue] ), 20, "sales_y" ),
				    ( "Avg Cupping Score", NAMEOF ( [Avg Cupping Score] ), 30, "quality_y" ),
				    ( "Wholesale Margin %", NAMEOF ( 'Sales Measures'[Wholesale Margin %] ), 40, "sales_y" )
				}
```

Each tuple is `( display name, NAMEOF ( measure ), sort ordinal, category )`.
`NAMEOF` is what makes the pattern robust: it is a *reference*, not a string,
so renaming a measure updates the parameter automatically. The fourth column
lets you group measures in slicers; the styler ignores it.

Two conventions worth keeping:

- **Space out the ordinals** (10, 20, 30…) so you can insert later without
  renumbering.
- **Comment out retired measures** (`--` or `//`) instead of deleting them —
  the history stays readable, and the styler knows to skip them.

## Step 2 — Declare the dimensions: `x-Plot Specific 1` and `2`

Repeat the exercise for dimensions. `x-Plot Specific 1` holds what a chart
can be sliced by on its axis; `x-Plot Specific 2` holds what it can be split
by in the legend:

```
	partition 'x-Plot Specific 1' = calculated
		mode: import
		source =
				{
				    ( "Month", NAMEOF ( 'Calendar'[Month] ), 10, "time_x" ),
				    ( "Quarter", NAMEOF ( 'Calendar'[Quarter] ), 20, "time_x" ),
				    ( "Origin Country", NAMEOF ( 'Beans'[Origin Country] ), 30, "bean_x" ),
				    ( "Roast Level", NAMEOF ( 'Beans'[Roast Level] ), 40, "bean_x" )
				}
```

```
	partition 'x-Plot Specific 2' = calculated
		mode: import
		source =
				{
				    ( "Channel", NAMEOF ( 'Orders'[Channel] ), 10, "order_x" ),
				    ( "Brew Method", NAMEOF ( 'Orders'[Brew Method] ), 20, "order_x" )
				}
```

The surrounding column definitions are identical to step 1 (rename
`y-Plot Specific` accordingly).

## Step 3 — Build the combo-chart page

On a new report page:

1. Add a **Line and clustered column chart**.
2. Bind its wells to the parameters: **X-axis** ← `x-Plot Specific 1`,
   **Legend** ← `x-Plot Specific 2`, **Column y-axis** ← `y-Plot Specific`.
   For a comparison line, put a second measure from `y-Plot Specific` on the
   **Line y-axis**.
3. Add three slicers, one per parameter table, so viewers choose what is
   plotted.
4. (Optional) Save bookmarks for the slicer combinations you present most —
   each bookmark now replaces what used to be a dedicated page.

Save the project so the PBIP folders are up to date.

> **Tip — one measure, one axis.** Avoid projecting the *same* measure on
> both the column and the line axis. Power BI applies per-measure formatting
> only once per visual and cannot disambiguate axes, so the second projection
> falls back to default rendering. Use a distinct (wrapper) measure instead.

## Step 4 — Preview the styling

From the folder that contains your PBIP project:

```bash
pbi-plot-styler "Roastery.Report" --dry-run
```

You get a unified diff of every `visual.json` the styler would rewrite:

```
Model:    .../Roastery.SemanticModel
Measures: 4 drive the styling

--- definition/pages/monthlyperformance/visuals/combo01/visual.json
+++ definition/pages/monthlyperformance/visuals/combo01/visual.json (styled)
...
2/2 visual(s) would change.
```

Nothing has been written yet — dry-run exits with code 1 to signal drift,
which also makes it a ready-made CI gate.

## Step 5 — Apply

```bash
pbi-plot-styler "Roastery.Report"
```

```
  styled definition/pages/monthlyperformance/visuals/combo01/visual.json
  styled definition/pages/seasonaltrends/visuals/combo02/visual.json

Restyled 2/2 visual(s); 0 already styled.
```

Open the report in Power BI Desktop: every measure the field parameters
expose now renders with the same line color, and its data labels sit on a
readable background. Run the command again and it reports
`Restyled 0/2 visual(s)` — the operation is idempotent.

## Step 6 — Make it yours

Drop a `plotstyler.toml` next to your project and pick your brand colors:

```toml
[style]
line_color = "#7A4419"
label_color = "#FFF8F0"
label_transparency = 30
```

```bash
pbi-plot-styler "Roastery.Report" --zip roastery-styled.zip
```

The `--zip` flag additionally emits the styled report folder as an archive
you can hand to whoever publishes it.

## Where to next

- Every flag and config key: [CLI reference](../reference/cli.md).
- Why this pattern scales where hand-formatting does not:
  [Field-parameter reporting](../explanation/field-parameter-reporting.md).

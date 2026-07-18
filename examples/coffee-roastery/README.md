# Coffee Roastery — a runnable before/after example

A complete, openable [PBIP](https://learn.microsoft.com/power-bi/developer/projects/projects-overview)
project you can open in Power BI Desktop to *see* what `pbi-plot-styler`
does. Everything here is fictional — a small coffee-roastery model with
inline data, so it refreshes offline with no data source, gateway, or
credentials.

It is deliberately shipped **unstyled**: the two combo charts use Power BI's
default series colors and have no data labels. Run the styler and they gain
your line colors, data-label colors, and label backgrounds — a visible,
one-command change.

## What's in the box

```
coffee-roastery/
  Roastery.pbip                      ← open THIS in Power BI Desktop
  Roastery.SemanticModel/
    definition.pbism
    definition/
      model.tmdl                     ← model + table refs
      database.tmdl
      relationships.tmdl             ← Orders/Lots → Calendar, Orders/Lots → Beans
      tables/
        Calendar.tmdl                ← inline data (#table), no CSV/gateway
        Beans.tmdl
        Orders.tmdl
        Lots.tmdl
        Sales Measures.tmdl          ← Revenue, Bags Sold #, Wholesale Margin %, …
        Quality Measures.tmdl        ← Avg Cupping Score, Defect Rate %
        x-Plot Specific 1.tmdl       ← axis field parameter (Month, Quarter, Origin Country, …)
        x-Plot Specific 2.tmdl       ← legend field parameter (Channel, Brew Method, Grind)
        y-Plot Specific.tmdl         ← values field parameter (the measures above)
  Roastery.Report/
    definition.pbir                  ← byPath → ../Roastery.SemanticModel
    definition/
      report.json
      pages/
        monthlyperformance/          ← combo01 + a slicer
        seasonaltrends/              ← combo02
```

Two pages, each with a `lineClusteredColumnComboChart` bound to the three
field parameters. The field-parameter tables are named exactly what the CLI
expects by default (`x-Plot Specific 1`, `x-Plot Specific 2`,
`y-Plot Specific`), so no `--table` override is needed.

## Run the styler

The styler runs **anywhere Python runs** — Windows, macOS, or Linux. Point it
at the report folder; the paired semantic model is resolved automatically from
`definition.pbir`.

First, see what it *would* do without touching anything:

```bash
# bash / macOS / Linux
pbi-plot-styler examples/coffee-roastery/Roastery.Report --dry-run
```

```powershell
# PowerShell / Windows
pbi-plot-styler examples\coffee-roastery\Roastery.Report --dry-run
```

You'll see a unified diff adding a `dataPoint` array (one series color per
measure) and a `labels` array (data labels on, text color, and a background
per measure) to both `combo01` and `combo02`, and:

```
2/2 visual(s) would change.
```

## See it in Power BI Desktop — the before/after

Opening a `.pbip` to verify the visuals needs **Windows with Power BI
Desktop** (Desktop is Windows-only). The styling itself does not — only this
final "look at the chart" step is Windows-bound.

**1. Copy the example** (so you keep a pristine "before" to compare against):

```bash
# bash / macOS / Linux
cp -r examples/coffee-roastery /tmp/roastery-demo
```

```powershell
# PowerShell / Windows
Copy-Item -Recurse examples\coffee-roastery $env:TEMP\roastery-demo
```

**2. Open the BEFORE.** Open `roastery-demo/Roastery.pbip` in Power BI
Desktop. On each page, look at the combo chart: the columns and line are in
Power BI's **default** theme colors and there are **no data labels**. Play
with the three slicers (axis / legend / values) — every field-parameter
combination is unstyled the same way. Close Desktop.

**3. Run the styler on the copy:**

```bash
# bash / macOS / Linux
pbi-plot-styler /tmp/roastery-demo/Roastery.Report
```

```powershell
# PowerShell / Windows
pbi-plot-styler $env:TEMP\roastery-demo\Roastery.Report
```

```
Restyled 2/2 visual(s); 0 already styled.
```

**4. Open the AFTER.** Re-open `roastery-demo/Roastery.pbip`. Now every series
shares your configured **line color** (default `#118DFF`), data labels are
**on** with your text color, and each label sits on a colored **background**.
Switch measures with the values slicer — every measure is styled, because the
styler wrote one entry per field-parameter measure, not per hand-picked
series.

Run the styler a second time and it reports `Restyled 0/2 visual(s); 2
already styled` — it is idempotent, safe to run after every model change.

## Try your own colors

```bash
pbi-plot-styler /tmp/roastery-demo/Roastery.Report \
  --line-color "#7A4419" --label-color "#FFF8F0" --label-transparency 30
```

Or drop a `plotstyler.toml` next to where you run it; see the top-level
[README](../../README.md#configuration) for every knob.

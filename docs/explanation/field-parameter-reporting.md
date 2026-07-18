# Field-parameter reporting

This page explains the reporting pattern `pbi-plot-styler` is built for: why
field parameters beat per-visual hand-formatting, how one page with bookmarks
replaces dozens of static pages, and why the last mile — formatting — has to
be enforced by a tool rather than by discipline.

## The failure mode of conventional reports

A conventional Power BI report treats the *page* as the unit of analysis.
Each question gets a page; each page gets hand-built visuals. This works
beautifully for the first five pages and then begins to rot:

- **Duplication.** "Revenue by month" and "Orders by month" are the same
  chart with a different measure, yet they are maintained as two artifacts.
- **Drift.** Formatting decisions — colors, label styles, axis settings —
  are stored *per visual*. Change your mind about label backgrounds and you
  are re-opening every page.
- **Asymmetric cost.** Adding a metric to the model takes a minute; giving
  it a presentable home in the report takes an afternoon. So new metrics
  lag, or ship unformatted.

The root cause is that the report encodes *content* (which measure, which
dimension) and *presentation* (how it looks) in the same hand-edited place.

## What field parameters change

A field parameter is a small calculated table whose rows are field
*references* — `NAMEOF ( [Revenue] )` — plus a display name, a sort ordinal,
and (by convention) a category. Bind a visual's well to the parameter and a
slicer decides, at view time, which field fills the well.

The template this project proposes uses exactly three:

- **`x-Plot Specific 1`** — every dimension a chart can be sliced by on its
  axis (time grains first, then entity attributes).
- **`x-Plot Specific 2`** — every dimension a chart can be split by in the
  legend.
- **`y-Plot Specific`** — every measure a chart can display.

With those in place, one combo-chart page becomes the whole reporting
surface. The viewer composes the chart they need from three slicers; a
*bookmark* captures any composition worth naming. "Revenue by month by
channel" stops being a page you maintain and becomes a bookmark — a saved
slicer state that costs nothing to keep and nothing to delete.

The economics invert. The model becomes the single place where analysts make
declarations ("this measure is plottable"), and the report becomes a
generic, reusable lens over those declarations. Adding the twenty-first
metric costs the same as adding the first: one tuple in a TMDL file.

Declaring the lists in the model rather than clicking them together in the
report has a further advantage: the parameter tables live in version control
as readable DAX. A pull request that adds a measure to `y-Plot Specific` is
one visible line; ordinals encode presentation order; commented-out tuples
document retirement without losing history.

## Why formatting must be enforced by a tool

There is one part of the visual that field parameters cannot reach. Power BI
stores per-measure formatting — series color, data-label background — as
selector arrays *inside each visual's `visual.json`*, keyed by measure name:

```json
{
  "properties": { "fill": { "solid": { "color": { "expr": { "Literal": { "Value": "'#118DFF'" } } } } } },
  "selector": { "metadata": "Sales Measures.Revenue" }
}
```

Those arrays are invisible in the Desktop UI beyond one-measure-at-a-time
format panes, and they do not follow the model:

- Add a measure to `y-Plot Specific` and it plots — with default styling,
  no label background, unreadable over columns.
- Rename a measure and its old selector entry stays behind, dead weight
  that silently stops matching.
- Ask two people to format two visuals and you get two interpretations of
  the style guide.

Discipline does not fix this, because the failure is structural: the
formatting lives in a place humans do not review, keyed by strings humans
rename. The reliable fix is the one used everywhere else in software when a
derived artifact must track a source of truth: **regenerate it**.

That is the whole design of `pbi-plot-styler`. The field-parameter tables
are the source of truth; the formatting arrays are build outputs. The tool
wipes them and rebuilds one entry per declared measure, sorted, from a
single configuration. Three properties follow:

- **Determinism.** Same model + same config = byte-identical output.
  Formatting diffs in review are always intentional.
- **Idempotency.** Re-running is free, so "run the styler" can sit at the
  end of every model change without thought.
- **Self-healing.** Renames and removals are not special cases; the stale
  state is discarded wholesale on every run.

The `--dry-run` mode closes the loop: it exits non-zero when a report has
drifted from its model, which turns the style guide into a CI check instead
of a code-review comment.

## A quirk worth knowing

Power BI applies a `selector.metadata` entry once per visual, even when the
same measure is projected on both the column axis and the line axis of a
combo chart. The columns win; the line falls back to default rendering, and
the PBIP schema offers no per-axis disambiguation. The practical rule:
never put the same measure on both axes — use a thin wrapper measure
(`Revenue (Line) = [Revenue]`) if you genuinely need the same value twice.

## Trade-offs, honestly

The pattern is not free. Slicer-driven pages feel less curated than a
hand-crafted executive dashboard; if a report's audience never composes
views, a static page may serve them better. Field parameters also cap
per-measure expressiveness: this template deliberately styles all measures
uniformly, because a deck of plots that differ only in their data is easier
to read than twenty bespoke charts. If a specific measure truly demands
bespoke formatting, give it its own visual outside the styler's targets —
the tool only rewrites the visual types you configure.

Within its lane — recurring, metric-by-metric performance reporting that
ends up pasted into decks — the combination of three field parameters, one
combo-chart page, bookmarks, and a formatter that enforces the style guide
turns report maintenance from a chore into a `git diff`.

# Launch material — pbi-plot-styler

Draft copy for X/Twitter and LinkedIn. Everything here is grounded in the
README, the release notes, and the bundled coffee-roastery example. No
invented metrics — the claims are about what the tool deterministically does,
not about time or money saved.

---

## Positioning tagline

**Stop hand-formatting Power BI charts. Style every combo chart from your
model's field parameters — with one command.**

Alternates:
- *Presentation-ready Power BI combo charts, by declaration.*
- *Your semantic model already knows which measures it plots. Now it styles
  them too.*

---

## Problem → solution hook

**The pain:** Most Power BI reports grow one page at a time. A new metric
arrives, someone copies a page, swaps the measure, re-formats the visuals by
hand. Twenty metrics later you maintain twenty near-identical pages, no two
formatted alike, and every style decision has to be re-made twenty times.

**The better shape:** one page, driven by three field parameters (axis,
legend, values) declared in the semantic model. Viewers compose the chart they
need at view time; a bookmark names any composition worth keeping.

**The catch field parameters can't fix:** per-measure series colors and
data-label backgrounds live inside each visual's `visual.json`, keyed by
measure name. They don't follow the model. Add a measure and it plots
unstyled; rename one and a dead entry lingers.

**The fix:** `pbi-plot-styler` reads the measures your field-parameter tables
declare and rebuilds every combo chart's `dataPoint[]` (series fill) and
`labels[]` (data-label color + per-measure background) arrays from scratch —
deterministic, idempotent, self-healing.

---

## X / Twitter launch thread (7 posts)

**1/**
Power BI report smell: twenty near-identical pages, one per metric, no two
formatted alike. Every new measure = another page to copy, re-bind, and
re-format by hand.

I built a small tool to kill the "re-format by hand" step. 🧵

**2/**
The fix starts in the model, not the report. One page, three field
parameters:

• x-Plot Specific 1 → axis
• x-Plot Specific 2 → legend
• y-Plot Specific → values

One combo chart bound to all three. Viewers compose the chart at view time.
Adding metric #21 costs one line of TMDL.

**3/**
But field parameters have a blind spot: per-measure formatting.

Series colors and data-label backgrounds live inside each visual's
visual.json, keyed by measure name — they don't follow the model. Add a
measure and it plots unstyled. Rename one and a dead entry sticks around.

**4/**
`pbi-plot-styler` closes the gap. Point it at a PBIP report folder:

```
pbi-plot-styler Roastery.Report
```

It reads the measures your field-parameter tables declare and rebuilds two
arrays on every combo chart — dataPoint[] (series fill) and labels[] (label
color + per-measure background).

**5/**
Concrete demo — the bundled coffee-roastery example ships deliberately
unstyled. One config file (green line, white label text on a green
background), one command, and every measure on both combo charts is styled the
same way. No colors clicked by hand in Desktop.

**6/**
It's built to be safe to run on every model change:

• Deterministic — same model + config = byte-identical output
• Idempotent — re-running a styled report is a no-op
• Self-healing — stale entries for renamed/retired measures are discarded

**7/**
And it's CI-ready. `--dry-run` prints a unified diff and exits 1 on drift, 0
when everything's in style — so a PR that adds a measure without re-styling
fails the gate.

Python 3.10+, MIT-licensed, `pip install .`
Try it on the coffee-roastery example in the repo. ☕

---

## LinkedIn post (~250 words)

**One command to make every Power BI combo chart presentation-ready.**

Most Power BI reports grow one page at a time. A new metric shows up, someone
copies a page, swaps the measure, and re-formats the visuals by hand. Twenty
metrics later you're maintaining twenty near-identical pages — no two
formatted quite alike — and every styling decision has been re-made twenty
times.

There's a better shape for recurring, metric-by-metric reporting: one page
driven by three field parameters (axis, legend, values) declared in the
semantic model. One combo chart, one matrix, three slicers. Viewers compose
the chart they need at view time, and a bookmark captures any composition
worth naming. Adding the twenty-first metric costs the same as the first: one
line of TMDL.

The one thing field parameters can't reach is per-measure formatting. Series
colors and data-label backgrounds are stored inside each visual, keyed by
measure name — they don't follow the model. Add a measure and it plots
unstyled; rename one and a dead entry lingers.

That's what `pbi-plot-styler` fixes. It reads the measures your field-parameter
tables declare and rebuilds each combo chart's series fills and data-label
formatting from scratch — deterministic, idempotent, and self-healing. There's
a runnable coffee-roastery example in the repo: it ships unstyled, and one
command turns every measure into a green line with white labels on a green
background.

It has a CI-grade `--dry-run` too, so drift from your style guide fails a pull
request instead of shipping.

Python 3.10+, MIT-licensed. Feedback and issues welcome.

---

## 5 one-liner hooks

1. Twenty metrics, twenty pages, no two formatted alike — pick a different
   shape.
2. Your field parameters decide which measures plot. Now they decide how those
   measures look.
3. Field parameters can't reach per-measure formatting. This CLI can.
4. Deterministic, idempotent, self-healing: run it after every model change and
   stop thinking about chart colors.
5. `--dry-run` turns your style guide into a CI gate — drift fails the PR.

---

## Hashtags

Primary: `#PowerBI` `#DataViz` `#BusinessIntelligence`

Secondary / rotate: `#PBIP` `#FieldParameters` `#Analytics` `#DAX`
`#DataEngineering` `#OpenSource` `#Python` `#ReportDesign` `#MicrosoftFabric`

---

## Demo asset checklist (for the before/after visual)

The strongest single asset is the coffee-roastery before/after, all true and
reproducible from the repo:

- **Before:** open `examples/coffee-roastery/Roastery.pbip` — combo charts in
  Power BI's default colors, no data labels.
- **Command:** `pbi-plot-styler Roastery.Report` (with the example's
  `plotstyler.toml`: green `#107C10` line/column fill, white `#FFFFFF` label
  text on a green `#107C10` background, fully opaque).
- **After:** re-open the report — every measure now shows the green line and
  white-on-green labels, applied by declaration rather than by hand.
- Pair the screenshots with the one-command terminal output for the reveal.

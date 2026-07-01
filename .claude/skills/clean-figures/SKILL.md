---
name: clean-figures
description: >-
  Create clean, presentable, Anthropic-styled charts and figures with
  matplotlib. Use this skill WHENEVER the user wants to generate, build,
  redesign, clean up, declutter, or fix any graph, chart, plot, figure, or data
  visualization — bar charts, scatter plots, line charts, grouped/stacked bars,
  heatmaps, subplot grids, and scientific figures. ESPECIALLY trigger when
  figures look messy, cluttered, or hard to read: overlong or multi-line titles,
  heavy captions, tiny fonts, overlapping or unreadable axis labels, annotations
  crammed onto every bar or point, internal notes or file paths leaking into the
  figure, titles getting cut off, or the same series getting different colors
  across figures. Also use it whenever the user asks to make a figure
  "presentable", "cleaner", "publication-ready", or "look like Anthropic /
  on-brand", even if they never say "chart". Prefer this skill over ad-hoc
  matplotlib whenever a figure is the deliverable.
---

# Clean figures

Make figures that read in seconds and match Anthropic's look. Most "messy"
figures are a **hierarchy problem**, not a data problem: the title is doing the
caption's job, the bars are doing a table's job, and the methods notes are doing
nobody any favors.

This skill ships a helper, `scripts/cleanplot.py`, that bakes in the Anthropic
theme, a locked model→color registry, and a layout engine that can't clip. Use
it — don't hand-tune `rcParams` from scratch.

## Three rules that do most of the work

### 1. On the figure: title + axes + graph. Nothing else.

A presentable figure carries only its **headline, its axis labels, and the
plot** (the plot includes its error bars / CIs — that's data, keep it).

Everything else — sample sizes, filters, the statistical method, what the error
bars mean, footnote daggers — goes in the **document's figure caption**, the
text you typeset *around* the image in the paper/post/deck. It does not get
stamped on the canvas. `caption()` exists for a rare one-line source note, but
**default to leaving it empty**. A subtitle is optional and should be short and
infrequent; usually the axis labels already supply the context.

> This is the correct publishing convention *and* the Anthropic look: the image
> stays clean; the prose carries the methods. If the user needs caption text,
> offer to write it as a separate paragraph rather than putting it on the image.

**Never put on the canvas:** file paths (`figures/3p1_complex_hints/`), internal
refs (`msg 7a`, ticket IDs), status notes (`DEMOTED`, `pending`, `TODO`, `WIP`),
raw debug values printed beside the clean value, or an empty panel containing a
paragraph that explains why it's empty.

### 2. Same series = same color, in every figure.

Color must be consistent across a whole figure series so they're comparable at a
glance. For the models in this project, the colors are **locked** in
`cleanplot` — always get them through:

```python
ax.bar(x, vals, color=cp.model_colors(models))   # or cp.model_color(name)
```

`model_color()` normalizes labels, so `"opus-4.8 (struct no-CoT†)"`,
`"gemini-2.5-flash (paper)"`, and `"gemini-3.1-pro (gen-only‡)"` map to their
base model. Unknown models get a distinct color that stays stable for the run;
pin anything new with `cp.register_model_colors({"my-model": "#788c5d"})`. For
non-model categories, lock a mapping once with `cp.color()` and reuse it.

### 3. Match Anthropic's look (it's the default).

`cp.set_style()` applies it: ivory background (`#faf9f5`), slate text
(`#141413`), a warm muted categorical palette with the clay accent (`#d97757`,
which is Opus's locked color), minimal chrome (no top/right spines, faint
gridlines), sans headings, and a **left-aligned bold title**. No pure white or
pure black surfaces. Pass `theme="plain"` only if a figure must sit on a white
page or needs maximum print contrast.

## Other rules

**Title.** One short line, plain language, ≤ ~60 characters. No methods, no
formulas, no "Fig 5 —" prefix unless a venue requires it.

**Fonts.** Use `cp.set_style()`. Ticks never below ~9 pt. For slides or figures
that will be shrunk, call `cp.set_style(scale=1.2)` — bigger, not smaller.

**Axis labels.** Words with units, not raw variable names or formulas (a formula
like `y = (unfaithful − base)/(follow − base)` is caption prose, not a y-label).

**Crowded category axes.** Labels must not overlap. In order of preference:
(1) **switch to a horizontal bar chart** (`ax.barh`) — best for many or long
names; (2) wrap onto two lines; (3) rotate 30°. `cp.tidy_xaxis(ax)` does (2)/(3)
automatically. For `categories × groups` that still won't fit (e.g. models ×
levels), use a **heatmap** with in-cell values instead of a bar forest.

**Annotation discipline.** Don't stamp numbers on every element. `cp.label_bars()`
labels at most ~12 bars and no-ops beyond that. For dense per-cell numbers (CI,
n, raw), use `cp.value_table()` or a heatmap — never floating text that collides
with error bars and ticks.

**Small-multiples (subplot grids).** Share axes (`sharey=True`) so panels are
comparable; give the grid **one** shared legend via `finalize()`'s legend
arguments, not one per panel; keep scales identical; light gray panel titles.

**Layout & export.** Always end with `cp.finalize(fig, path)`. It reserves
header/legend/footer bands so text can't overlap the plot, then saves with
`bbox_inches="tight"` so nothing clips. PNG at ≥ 200 DPI (default) or `.pdf` /
`.svg` for vector. Sizes: ~8×5 in single chart, ~8×6 scatter, wider for grids.

## Workflow

1. **Read the helper.** Open `scripts/cleanplot.py` (top docstring) for the real
   function names. For horizontal-bar conversion, heatmaps, dense-number tables,
   grouped/dual-arm layouts, palettes, or export sizing, read
   `references/recipes.md`.
2. **Plot the data**, pulling colors from `cp.model_colors()` (models) or
   `cp.color()` / `cp.colors()` (other categories).
3. **Apply the hierarchy:** `cp.set_style()` first; then `cp.title(...)`, axis
   labels (words + units); `cp.tidy_xaxis()` for categories; `cp.label_bars()`
   or `cp.value_table()` for numbers. Leave the caption empty.
4. **Run the pre-flight checklist** and fix anything that fails.
5. **Finalize:** `cp.finalize(fig, "name.png")`, then present the file. If the
   user needs methods text, write it as a separate caption paragraph.

A minimal end-to-end example is the "copy-paste skeleton" in
`references/recipes.md` — follow it rather than reinventing setup.

## Pre-flight checklist

- [ ] Only title + axis labels + plot on the canvas; caption empty (or one short
      line); any subtitle short and necessary.
- [ ] Methods / n / CI-definition are in the document caption, not on the image.
- [ ] No file paths, ticket/message refs, or status notes anywhere.
- [ ] Every series uses its locked color via `model_color()` /
      `model_colors()`; the same series is the same color in every figure.
- [ ] Anthropic theme applied (ivory ground, slate text, muted palette); no pure
      white/black surfaces.
- [ ] Title is one short line; smallest text still comfortably readable.
- [ ] No x-axis labels overlap (wrapped, rotated, or switched to `barh`).
- [ ] No numeric label collides with an error bar, another label, or an axis.
- [ ] Error bars / CIs present on the plot.
- [ ] Axis labels are words with units, not variable names or formulas.
- [ ] A subplot grid shares scales and has exactly one shared legend.
- [ ] Saved via `cp.finalize()`; open the file and confirm nothing clips.

## Note on scope

The helper targets matplotlib because that is what produces these figures, but
the hierarchy, consistent-color, and minimal-caption principles transfer to
seaborn, plotly, or ggplot. In another tool, apply the same rules and the same
Anthropic tokens (ivory `#faf9f5`, slate `#141413`, clay `#d97757`) by hand.

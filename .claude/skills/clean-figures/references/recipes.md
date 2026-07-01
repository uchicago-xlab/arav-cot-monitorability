# cleanplot recipes

Concrete patterns for `scripts/cleanplot.py`. Every snippet assumes:

```python
import sys; sys.path.insert(0, ".claude/skills/clean-figures/scripts")  # or wherever cleanplot lives
import cleanplot as cp
import matplotlib.pyplot as plt
import numpy as np
```

`cp.SLATE`, `cp.IVORY`, `cp.CLAY`, `cp.MUTED`, `cp.GRID`, `cp.PALETTE` are exposed for the rare
hand-drawn element. The locked model registry lives in `cp._MODEL_COLORS` (read it to see what's
pinned; add with `cp.register_model_colors`).

---

## Copy-paste skeleton (the default a figure should start from)

```python
cp.set_style()                                   # 1. theme FIRST

models = ["gemini-2.5-flash", "gemini-3-flash", "gpt-5.5", "gpt-oss-120b", "opus-4.8"]
vals   = [0.09, 0.38, 0.42, -0.01, 0.16]
err    = [0.06, 0.06, 0.09, 0.03, 0.06]          # 2σ half-widths

fig, ax = plt.subplots(figsize=(8, 5))           # 2. plot the data
bars = ax.bar(range(len(models)), vals, color=cp.model_colors(models), edgecolor="none")
ax.errorbar(range(len(models)), vals, yerr=err, fmt="none", ecolor=cp.SLATE, capsize=3, lw=1)
ax.axhline(0, color=cp.SLATE, lw=0.8)
ax.set_xticks(range(len(models))); ax.set_xticklabels(models)
ax.set_ylabel("unfaithfulness Δ (vs no-hint baseline)")   # words + units, not a formula

cp.tidy_xaxis(ax)                                # 3. hierarchy
cp.label_bars(ax, bars, yerr=err)               #    yerr → labels clear the whiskers
cp.title(fig, "Simple-hint unfaithfulness replicates",
         "§3.1 · GPQA · higher = follows the hint without admitting it")

cp.finalize(fig, "figures/clean/headline.png")   # 4. reserve bands + save tight
```

Methods (n, filter, CI definition) do **not** go on the canvas — they go in the prose caption you
write around the image. Leave `cp.caption()` unset unless you need a one-line source note.

---

## Crowded category axis → horizontal bars (`barh`)

Many models, or long names, or `models × levels` packed into one axis = a "bar forest" with
overlapping labels. First choice is **horizontal**: names go on the y-axis where they have room.

```python
cp.set_style()
order = models[::-1]                              # top-to-bottom reads best reversed
y = range(len(order))
fig, ax = plt.subplots(figsize=(8, 0.5 * len(order) + 2))
ax.barh(y, [d[m] for m in order], color=cp.model_colors(order), edgecolor="none")
ax.set_yticks(list(y)); ax.set_yticklabels(order)
ax.grid(axis="x"); ax.grid(axis="y", visible=False)   # gridlines follow the value axis
ax.set_xlabel("decode-uplift (with-CoT − no-CoT accuracy)")
cp.title(fig, "Which models need to externalize the decode")
cp.finalize(fig, "figures/clean/uplift_barh.png")
```

If it's `categories × groups` (e.g. models × 3 levels) and *still* won't fit, use a **heatmap**.

---

## Heatmap with in-cell values (the answer to models × levels)

```python
cp.set_style()
actors = ["gemini-3-flash", "gpt-5.5", "gpt-oss-120b"]
levels = ["L1", "L2", "L3"]
grid = np.array([[0.80, 0.60, 0.10], [0.20, 0.60, 0.50], [0.05, 0.00, 0.10]])

fig, ax = plt.subplots(figsize=(6, 4))
im = ax.imshow(grid, cmap="RdYlGn", vmin=-0.5, vmax=1.0, aspect="auto")
ax.set_xticks(range(len(levels))); ax.set_xticklabels(levels)
ax.set_yticks(range(len(actors))); ax.set_yticklabels(actors)
ax.grid(visible=False)
for i in range(grid.shape[0]):
    for j in range(grid.shape[1]):
        ax.text(j, i, f"{grid[i, j]:+.2f}", ha="center", va="center",
                color=cp.SLATE, fontsize=9)
fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04, label="decode-uplift")
cp.title(fig, "Necessity map — uplift by model × level")
cp.finalize(fig, "figures/clean/heatmap.png")
```

Annotate each cell with its value (and a verdict glyph if a near-zero cell is ambiguous) so an
"empty" cell can't hide whether it's *one-shot* (no CoT needed) or *too-hard* (can't even with CoT).

---

## Dense per-cell numbers → `value_table`, not floating text

When you want raw k/n or CIs printed and they'd collide with bars/whiskers, attach a table to a
borderless axis instead of `ax.text` scattered across the plot:

```python
fig, (ax, axt) = plt.subplots(2, 1, height_ratios=[3, 1], figsize=(8, 6))
# ... draw bars on ax ...
axt.axis("off")
cp.value_table(axt, grid=[["9/10", "8/10", "6/10"], ["1/10", "2/10", "5/10"]],
               row_labels=["with-CoT", "no-CoT"], col_labels=levels)
cp.finalize(fig, "figures/clean/with_table.png")
```

---

## Grouped bars (categories × series) when a heatmap is overkill

Keep it to ≤ ~3 series and ≤ ~6 groups, else go heatmap. Color = the *series*, locked.

```python
cp.set_style()
groups, series = ["arithmetic", "iterated", "indirection"], ["L1", "L2", "L3"]
data = {"L1": [.8, .7, .7], "L2": [.6, .8, .8], "L3": [.1, .5, .8]}
x = np.arange(len(groups)); w = 0.8 / len(series)
fig, ax = plt.subplots(figsize=(8, 5))
for i, s in enumerate(series):
    ax.bar(x + (i - (len(series) - 1) / 2) * w, data[s], w,
           color=cp.color(s), edgecolor="none", label=s)
ax.set_xticks(x); ax.set_xticklabels(groups)
ax.set_ylabel("decode-uplift")
cp.title(fig, "Uplift by hint family")
cp.finalize(fig, "figures/clean/grouped.png",
            legend={s: cp.color(s) for s in series})   # one shared legend, in the footer band
```

---

## Line / scatter series (e.g. a difficulty sweep)

```python
cp.set_style()
fig, ax = plt.subplots(figsize=(8, 5))
for m in ["gemini-2.5-flash", "gemini-3-flash", "gpt-5.5"]:
    ax.plot(B_vals, adopt_rate[m], marker="o", color=cp.model_color(m), label=m)
ax.set_xlabel("difficulty B (operand magnitude)")
ax.set_ylabel("adopt rate (follows the planted wrong step)")
cp.title(fig, "Stronger models externalize later", "Follow-up C · adopt overtakes correct at higher B")
cp.finalize(fig, "figures/clean/sweep.png",
            legend=cp.legend_lines({m: cp.model_color(m) for m in models}, marker="o", lw=1.6))
```

`cp.legend_lines(mapping, **kw)` and `cp.legend_patches(mapping)` build handles from a
`{label: color}` map; pass either to `finalize(legend=...)`.

---

## Small-multiples (subplot grid)

```python
cp.set_style()
fams = ["arithmetic", "bignum", "iterated", "deductive", "indirection"]
fig, axes = plt.subplots(1, len(fams), figsize=(3 * len(fams), 4), sharey=True)  # shared scale
for ax, fam in zip(axes, fams):
    # ... draw the same chart per family ...
    ax.set_title(fam, color=cp.MUTED, fontsize=10)        # light gray panel titles
cp.title(fig, "Decode-uplift across hint families")
cp.finalize(fig, "figures/clean/families.png",
            legend={"CoT-necessary": "#1b9e77", "one-shot": "#5b7fa6", "too-hard": "#b0b0b0"})
# ONE shared legend via finalize, never one per panel; sharey keeps panels comparable.
```

---

## Export sizing

| figure | size (in) | notes |
|---|---|---|
| single bar/line chart | `8 × 5` | the default |
| scatter | `8 × 6` | square-ish |
| horizontal bars | `8 × (0.5·n + 2)` | grow height with the number of rows |
| heatmap | `~6 × 4` | wider if many columns |
| small-multiples row | `3·k × 4` | k = number of panels |

`cp.finalize` saves at **200 DPI** PNG by default; pass a `.pdf`/`.svg` path for vector, or
`dpi=300` for print. It always reserves header/legend/footer bands and saves with
`bbox_inches="tight"`, so titles and legends cannot clip — but still open the file and confirm.

For slides or anything that will be shrunk: `cp.set_style(scale=1.2)` (bigger text, never smaller).
For a figure that must sit on a white page: `cp.set_style(theme="plain")`.

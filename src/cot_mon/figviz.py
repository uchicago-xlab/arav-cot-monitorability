"""Shared decode-necessity plotting — the readable replacement for the old crushed-line fig3.

Both §3.1 figure scripts (`make_figures.py` → 3p1_replication, `make_complex_figures.py` →
3p1_complex_hints) draw the SAME decode-uplift bar so the necessity metric reads identically
across experiments. The finding IS the gap (with-CoT − no-CoT accuracy), so we plot the gap
directly as a bar with a Newcombe 2σ CI and a "necessity threshold" reference line — not two
near-overlapping lines the reader has to eyeball.

CRITICAL (figure-honesty): a near-zero uplift bar is AMBIGUOUS — one-shot (high no-CoT) vs too-hard
(low with-CoT) are opposite causes. We colour them distinctly and annotate every bar with its raw
(with-CoT, no-CoT) pair, so trivial and impossible never both render as a plain zero bar.

matplotlib lives here (not in the core library that tests import); the numeric helpers
(`wilson_diff_ci`, `decode_necessity_label`) stay in `metrics.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

from cot_mon import metrics  # noqa: E402

THRESHOLD = 0.5  # uplift ≥ this ⇒ the decode is CoT-necessary (paper's ≥50pp uplift bar)

# one colour/hatch per necessity verdict — the legend the reader decodes the bars with.
STYLE = {
    "cot_necessary": {"color": "#1b9e77", "hatch": None, "label": "CoT-necessary (uplift ≥ 0.5)"},
    "one_shot":      {"color": "#3182bd", "hatch": "..", "label": "one-shot (no-CoT high → no CoT needed)"},
    "too_hard":      {"color": "#b0b0b0", "hatch": "xx", "label": "too-hard (with-CoT low → can't even w/ CoT)"},
    "weak":          {"color": "#fdae61", "hatch": "//", "label": "weak (0 < uplift < 0.5)"},
}
GLYPH = {"cot_necessary": "✓", "one_shot": "1", "too_hard": "✗", "weak": "~"}


@dataclass
class Cell:
    """One decode cell: both arms' k/n at a given (actor, family, level)."""
    actor: str
    family: str
    level: str                 # "L1"/"L2"/"L3" or "simple"
    k_cot: int
    n_cot: int
    k_nocot: int
    n_nocot: int
    source: str = "fresh"      # "fresh" | "reused" — reused decode-calibration cells get a *

    @property
    def acc_cot(self) -> float:
        return self.k_cot / self.n_cot if self.n_cot else 0.0

    @property
    def acc_nocot(self) -> float:
        return self.k_nocot / self.n_nocot if self.n_nocot else 0.0

    @property
    def uplift(self) -> float:
        return self.acc_cot - self.acc_nocot

    @property
    def verdict(self) -> str:
        return metrics.decode_necessity_label(self.acc_cot, self.acc_nocot, threshold=THRESHOLD)

    @property
    def ci(self) -> tuple[float, float]:
        return metrics.wilson_diff_ci(self.k_cot, self.n_cot, self.k_nocot, self.n_nocot)


def _yerr(cell: Cell):
    lo, hi = cell.ci
    return [[max(0.0, cell.uplift - lo)], [max(0.0, hi - cell.uplift)]]


def draw_uplift_bars(ax, cells: list[Cell], *, group_attr: str, series: list[str],
                     group_order: list[str], group_label: dict, metric_label: str, title: str,
                     legend: bool = True):
    """Grouped decode-uplift bar chart. x = `group_attr` (actor or family); bars within a group =
    `series` (levels). Colour/hatch = necessity verdict; each bar annotated with its (with-CoT,
    no-CoT) pair. Threshold line at +0.5. Ports fig4's readability onto the necessity metric."""
    groups = [g for g in group_order if any(getattr(c, group_attr) == g for c in cells)]
    by = {(getattr(c, group_attr), c.level): c for c in cells}
    width = 0.8 / max(len(series), 1)
    for li, lv in enumerate(series):
        for gi, g in enumerate(groups):
            c = by.get((g, lv))
            if c is None:
                continue
            x = gi + (li - (len(series) - 1) / 2) * width
            st = STYLE[c.verdict]
            ax.bar(x, c.uplift, width=width, color=st["color"], hatch=st["hatch"],
                   edgecolor="black", linewidth=0.7)
            ax.errorbar(x, c.uplift, yerr=_yerr(c), fmt="none", ecolor="black", capsize=2.5, lw=1)
            top = c.uplift >= 0
            ax.text(x, c.uplift + (0.03 if top else -0.03),
                    f"{lv}{'*' if c.source == 'reused' else ''} ({c.acc_cot:.2f},{c.acc_nocot:.2f})",
                    ha="center", va="bottom" if top else "top", fontsize=5.6, rotation=90, color="#222")
    ax.axhline(THRESHOLD, color="#1b9e77", lw=1.2, ls="--", zorder=0)
    ax.text(len(groups) - 0.5, THRESHOLD + 0.015, "necessity threshold +0.5", ha="right",
            va="bottom", fontsize=7, color="#1b9e77")
    ax.axhline(0, color="black", lw=0.8)
    ax.set_xticks(range(len(groups)))
    ax.set_xticklabels([group_label.get(g, g) for g in groups], fontsize=8.5)
    ax.set_ylabel(f"decode-uplift = with-CoT − no-CoT\n({metric_label})")
    ax.set_ylim(min(-0.6, ax.get_ylim()[0]), 1.22)   # headroom for the rotated (wCoT,noCoT) annotations
    ax.set_title(title, fontsize=9.5)
    if legend:
        ax.legend(handles=verdict_legend_handles(cells), fontsize=6.8, loc="lower right", framealpha=0.92)


def verdict_legend_handles(cells: list[Cell]):
    """Legend patches for the verdicts present in `cells` (+ the reused marker) — shared by the
    per-axes legend and the figure-level legend in the faceted complex figure."""
    seen = [k for k in STYLE if any(c.verdict == k for c in cells)]
    handles = [Patch(facecolor=STYLE[k]["color"], hatch=STYLE[k]["hatch"], edgecolor="black",
                     label=STYLE[k]["label"]) for k in seen]
    if any(c.source == "reused" for c in cells):
        handles.append(Patch(facecolor="white", edgecolor="grey", label="* reused decode calibration"))
    return handles


def draw_necessity_heatmap(ax, cells: list[Cell], *, family: str, levels: list[str],
                           actor_order: list[str], actor_label: dict, show_ylabels: bool = True):
    """One family's (actor × level) decode-uplift heatmap; each cell annotated with the uplift +
    a verdict glyph (✓ CoT-necessary, 1 one-shot, ✗ too-hard, ~ weak) so one-shot and too-hard
    never read as the same blank zero."""
    fam_cells = [c for c in cells if c.family == family]
    actors = [a for a in actor_order if any(c.actor == a for c in fam_cells)]
    by = {(c.actor, c.level): c for c in fam_cells}
    grid = np.full((len(actors), len(levels)), np.nan)
    for ai, a in enumerate(actors):
        for li, lv in enumerate(levels):
            c = by.get((a, lv))
            if c is not None:
                grid[ai, li] = c.uplift
    im = ax.imshow(grid, cmap="RdYlGn", vmin=-0.5, vmax=1.0, aspect="auto")
    ax.set_xticks(range(len(levels)))
    ax.set_xticklabels(levels, fontsize=8)
    ax.set_yticks(range(len(actors)))
    ax.set_yticklabels([actor_label.get(a, a) for a in actors] if show_ylabels else [""] * len(actors),
                       fontsize=8)
    ax.set_title(family, fontsize=9)
    for ai, a in enumerate(actors):
        for li, lv in enumerate(levels):
            c = by.get((a, lv))
            txt = "—" if c is None else f"{c.uplift:+.2f}\n{GLYPH[c.verdict]}{'*' if c and c.source=='reused' else ''}"
            ax.text(li, ai, txt, ha="center", va="center", fontsize=7,
                    color="#888" if c is None else "black")
    return im


def save(fig, outdir, name: str) -> Path:
    Path(outdir).mkdir(parents=True, exist_ok=True)
    path = Path(outdir) / f"{name}.png"
    fig.savefig(path, dpi=130)
    plt.close(fig)
    return path

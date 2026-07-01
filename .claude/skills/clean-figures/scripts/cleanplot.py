"""cleanplot — Anthropic-styled, clip-proof matplotlib figures.

Bake in the look and the layout so figure scripts stop hand-tuning rcParams and
stop clipping titles. Import as `cp` and use these (the only public surface):

  STYLE
    set_style(theme="anthropic", scale=1.0)   apply theme + fonts (call FIRST)

  COLOR (consistency is the whole point — same series, same color, every figure)
    model_color(name)            -> hex   one model, label-normalized
    model_colors(names)          -> list  many models
    register_model_colors(dict)         pin new models (or override)
    color(key)                   -> hex   lock a non-model category color
    colors(keys)                 -> list  many categories

  HIERARCHY (title + axes + plot on the canvas; methods go in the doc caption)
    title(fig, text, subtitle=None)     left-aligned bold headline (+ short subtitle)
    caption(fig, text)                  rare one-line source note (default: none)
    tidy_xaxis(ax, ...)                 wrap / rotate crowded category labels
    label_bars(ax, ...)                 label <=12 bars; no-op beyond
    value_table(ax, grid, ...)          dense per-cell numbers as a side table

  EXPORT (reserves header/legend/footer bands so nothing overlaps or clips)
    finalize(fig, path, legend=..., dpi=200) -> Path

Design tokens (Anthropic): ivory ground #faf9f5, slate text #141413, clay accent
#d97757 (Opus's locked color). No pure white/black surfaces in the default theme.
"""
from __future__ import annotations

import re
import textwrap
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

# ── design tokens ─────────────────────────────────────────────────────────────
IVORY = "#faf9f5"   # background
SLATE = "#141413"   # primary text
CLAY = "#d97757"    # accent — Opus's locked color
GRID = "#e4e1d8"    # faint gridline on ivory
MUTED = "#6b6862"   # secondary text (subtitles, captions, annotations)

# Warm, muted categorical palette (clay leads). Used for unknown models + generic
# categories. Distinct enough to tell apart, desaturated enough to sit on ivory.
PALETTE = [
    CLAY,        # clay
    "#5b7fa6",   # muted blue
    "#7a9b76",   # sage green
    "#c29544",   # ochre
    "#9c6b8e",   # plum
    "#6b8e9e",   # slate teal
    "#b9785f",   # terracotta
    "#8a8d6b",   # olive
    "#7d7aa0",   # muted indigo
    "#a0726a",   # dusty rose-brown
]

# ── locked model → color registry ─────────────────────────────────────────────
# Same model is the same color in every figure of the project. Gemini family runs
# blue→teal, GPT warm, open-weights green/earth, Opus the clay accent.
_MODEL_COLORS: dict[str, str] = {
    "gemini-2.5-flash": "#9aa7b4",   # muted blue-grey (the paper analog)
    "gemini-2.5-pro": "#3f5d78",     # deep blue
    "gemini-3-flash": "#5b7fa6",     # muted blue
    "gemini-3.5-flash": "#6b8e9e",   # slate teal
    "gemini-3.1-pro": "#7d7aa0",     # muted indigo
    "gpt-5.5": "#c29544",            # ochre
    "gpt-oss-120b": "#7a9b76",       # sage green (open weight)
    "deepseek-v4-flash": "#b9785f",  # terracotta
    "qwen3": "#9c6b8e",              # plum
    "qwen3-235b": "#9c6b8e",
    "qwen3-30b": "#b08aa6",          # lighter plum (dev alt)
    "qwen3.5-122b": "#8a5f7e",       # deeper plum
    "kimi-k2-thinking": "#a0726a",   # dusty rose-brown
    "opus-4.8": CLAY,                # clay — locked
}
_DYNAMIC_MODEL: dict[str, str] = {}   # unknown models, stable for the process
_GENERIC: dict[str, str] = {}         # non-model category locks


def _norm(name: str) -> str:
    """Normalize a display label to a base-model key: drop parentheticals, daggers,
    newlines; unify separators. 'opus-4.8 (struct no-CoT†)' -> 'opus-4.8'."""
    s = str(name).strip().lower()
    s = s.split("(")[0].split("\n")[0]            # drop parentheticals / 2nd line
    s = re.sub(r"[†‡*§•…]+", "", s)               # drop footnote glyphs
    s = s.replace("_", "-").replace(" ", "-")     # unify separators
    s = re.sub(r"-+", "-", s).strip("-")
    return s


def register_model_colors(mapping: dict[str, str]) -> None:
    """Pin (or override) model colors. Keys are label-normalized, so pass any display form."""
    for k, v in mapping.items():
        _MODEL_COLORS[_norm(k)] = v


def model_color(name: str) -> str:
    """Locked color for one model label (normalized). Unknown → a stable palette color.
    Dots and dashes are equivalent, so the roster's snake_case 'gemini_2_5_flash' and the
    display 'gemini-2.5-flash (paper)' resolve to the same color."""
    lk = _norm(name).replace(".", "-")           # loose key: treat '.' and '-' alike
    lookup = {k.replace(".", "-"): v for k, v in _MODEL_COLORS.items()}
    if lk in lookup:
        return lookup[lk]
    # longest known base-model key this label starts with (e.g. opus-4.8-direct → opus-4.8)
    for known in sorted(lookup, key=len, reverse=True):
        if lk == known or lk.startswith(known + "-"):
            return lookup[known]
    if lk not in _DYNAMIC_MODEL:
        used = set(lookup.values()) | set(_DYNAMIC_MODEL.values())
        nxt = next((c for c in PALETTE if c not in used), PALETTE[len(_DYNAMIC_MODEL) % len(PALETTE)])
        _DYNAMIC_MODEL[lk] = nxt
    return _DYNAMIC_MODEL[lk]


def model_colors(names) -> list[str]:
    return [model_color(n) for n in names]


def color(key: str) -> str:
    """Lock a color for an arbitrary (non-model) category; stable within the process."""
    k = str(key).strip().lower()
    if k not in _GENERIC:
        used = set(_GENERIC.values())
        _GENERIC[k] = next((c for c in PALETTE if c not in used), PALETTE[len(_GENERIC) % len(PALETTE)])
    return _GENERIC[k]


def colors(keys) -> list[str]:
    return [color(k) for k in keys]


# ── style ─────────────────────────────────────────────────────────────────────
def set_style(theme: str = "anthropic", scale: float = 1.0) -> None:
    """Apply the theme + fonts. Call before plotting. `scale` enlarges all text
    (use >1 for slides/figures that will be shrunk — bigger, never smaller).

    Note: the sans fonts (Helvetica/Arial) lack some typographic glyphs (✓ ✗ → σ);
    those render as tofu boxes. Stick to ASCII/Latin-1 markers (× ~ · −) for on-canvas
    annotations, or spell verdicts out — see references/recipes.md."""
    base = 11 * scale
    plain = theme == "plain"
    bg = "#ffffff" if plain else IVORY
    plt.rcParams.update({
        "figure.facecolor": bg,
        "axes.facecolor": bg,
        "savefig.facecolor": bg,
        "text.color": SLATE,
        "axes.edgecolor": SLATE if plain else "#cfccc2",
        "axes.labelcolor": SLATE,
        "axes.titlecolor": SLATE,
        "xtick.color": SLATE,
        "ytick.color": SLATE,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "axes.grid.axis": "y",
        "grid.color": "#d6d3ca" if plain else GRID,
        "grid.linewidth": 0.8,
        "axes.axisbelow": True,
        "font.family": "sans-serif",
        "font.sans-serif": ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"],
        "font.size": base,
        "axes.titlesize": base * 1.0,
        "axes.titleweight": "regular",
        "axes.labelsize": base * 0.95,
        "xtick.labelsize": max(9, base * 0.85),
        "ytick.labelsize": max(9, base * 0.85),
        "legend.fontsize": max(9, base * 0.82),
        "legend.frameon": False,
        "axes.titlelocation": "left",
        "axes.titlepad": 8,
        "figure.dpi": 110,
    })


# ── hierarchy ─────────────────────────────────────────────────────────────────
def title(fig, text: str, subtitle: str | None = None) -> None:
    """Set the figure's left-aligned bold headline (one short line) + optional short
    subtitle. Rendered by finalize() in the reserved header band."""
    fig._cp_title = (str(text), str(subtitle) if subtitle else None)


def caption(fig, text: str) -> None:
    """Set a rare one-line source note at the very bottom. Default: leave unset —
    methods/n/CI definitions belong in the document's figure caption, not the canvas."""
    fig._cp_caption = str(text) if text else None


def tidy_xaxis(ax, wrap: int = 14, max_upright: int = 6) -> None:
    """Stop x-axis labels overlapping: wrap onto two lines, else rotate 30°. For many
    or long names prefer a horizontal bar chart (ax.barh) — see references/recipes.md."""
    texts = [t.get_text() for t in ax.get_xticklabels()]
    if not any(texts):
        return
    longest = max((len(t) for t in texts), default=0)
    n = len(texts)
    if n <= max_upright and longest <= wrap:
        return
    wrapped = ["\n".join(textwrap.wrap(t, wrap)) or t for t in texts]
    rotate = n > max_upright and longest > wrap
    ax.set_xticks(range(len(texts)) if not ax.get_xticks().size else ax.get_xticks())
    ax.set_xticklabels(wrapped, rotation=30 if rotate else 0,
                       ha="right" if rotate else "center", rotation_mode="anchor")


def label_bars(ax, bars=None, fmt: str = "{:.2f}", max_bars: int = 12,
               fontsize: float | None = None, yerr=None) -> None:
    """Label bar tops, but only when sparse (≤ max_bars); no-op beyond, so dense
    charts don't get a number stamped on every bar. Use value_table() for dense numbers.

    Pass `yerr` (scalar or per-bar) to place each label just beyond its error-bar
    whisker instead of on the bar top, so labels never collide with CIs."""
    patches = list(bars) if bars is not None else list(ax.patches)
    if len(patches) > max_bars:
        return
    fs = fontsize if fontsize is not None else max(8, plt.rcParams["font.size"] * 0.78)
    errs = ([yerr] * len(patches) if (yerr is None or not hasattr(yerr, "__len__")) else list(yerr))
    for p, e in zip(patches, errs):
        h = p.get_height()
        up = h >= 0
        whisker = h + (e or 0.0) if up else h - (e or 0.0)
        ax.annotate(fmt.format(h), (p.get_x() + p.get_width() / 2, whisker),
                    xytext=(0, 4 if up else -4), textcoords="offset points",
                    ha="center", va="bottom" if up else "top", fontsize=fs, color=SLATE)


def value_table(ax, grid, *, row_labels=None, col_labels=None, loc: str = "bottom",
                fmt: str = "{}") -> None:
    """Render dense per-cell numbers as a real table instead of floating text that
    collides with bars/ticks/CIs. `grid` is a 2-D list/array of values."""
    cells = [[("" if v is None else (v if isinstance(v, str) else fmt.format(v))) for v in row]
             for row in grid]
    tab = ax.table(cellText=cells, rowLabels=row_labels, colLabels=col_labels,
                   loc=loc, cellLoc="center", edges="open")
    tab.auto_set_font_size(False)
    tab.set_fontsize(max(8, plt.rcParams["font.size"] * 0.8))
    tab.scale(1, 1.3)
    for cell in tab.get_celld().values():
        cell.set_text_props(color=SLATE)
    return tab


# ── legend helpers ────────────────────────────────────────────────────────────
def legend_patches(mapping: dict[str, str]) -> list[Patch]:
    """Build legend handles {label: color} as filled patches (for categorical fills)."""
    return [Patch(facecolor=c, edgecolor="none", label=l) for l, c in mapping.items()]


def legend_lines(mapping: dict[str, str], **kw) -> list[Line2D]:
    """Build legend handles {label: color} as line markers (for line/scatter series)."""
    return [Line2D([0], [0], color=c, label=l, **kw) for l, c in mapping.items()]


# ── export ────────────────────────────────────────────────────────────────────
def finalize(fig, path, *, legend=None, legend_labels=None, legend_ncol: int | None = None,
             dpi: int = 200) -> Path:
    """Reserve header (title/subtitle) and footer (legend/caption) bands so text can
    never overlap the plot, then save tight so nothing clips. Returns the Path.

    `legend` may be a list of handles, or a {label: color} dict (rendered as patches).
    """
    scale = plt.rcParams["font.size"] / 11.0
    w_in, h_in = fig.get_size_inches()

    text, subtitle = getattr(fig, "_cp_title", (None, None))
    cap = getattr(fig, "_cp_caption", None)

    # legend handles
    handles, labels = None, None
    if isinstance(legend, dict):
        handles = legend_patches(legend)
        labels = list(legend.keys())
    elif legend is not None:
        handles = list(legend)
        labels = legend_labels

    # reserve bands (inches → fractions)
    top_in = (0.46 * scale if text else 0.0) + (0.30 * scale if subtitle else 0.0)
    if text or subtitle:
        top_in += 0.12
    ncol = legend_ncol or (min(len(handles), 4) if handles else 1)
    nrow = (len(handles) + ncol - 1) // ncol if handles else 0
    legend_in = (0.30 * scale + 0.24 * scale * nrow) if handles else 0.0
    cap_in = 0.24 * scale if cap else 0.0
    bot_in = legend_in + cap_in + (0.10 if (handles or cap) else 0.0)

    top = max(0.5, 1.0 - top_in / h_in)
    bottom = min(0.5, bot_in / h_in)
    try:
        fig.tight_layout(rect=(0.0, bottom, 1.0, top))
    except Exception:
        fig.subplots_adjust(top=top, bottom=bottom)

    if text:
        fig.text(0.012, 0.985, text, ha="left", va="top", color=SLATE,
                 fontsize=plt.rcParams["font.size"] * 1.35, fontweight="bold")
    if subtitle:
        fig.text(0.012, 0.985 - (0.5 * scale) / h_in, subtitle, ha="left", va="top",
                 color=MUTED, fontsize=plt.rcParams["font.size"] * 0.95)
    if handles:
        fig.legend(handles=handles, labels=labels, loc="lower center",
                   bbox_to_anchor=(0.5, cap_in / h_in), ncol=ncol,
                   frameon=False, handlelength=1.4, columnspacing=1.6)
    if cap:
        fig.text(0.5, 0.008, cap, ha="center", va="bottom", color=MUTED,
                 fontsize=plt.rcParams["font.size"] * 0.8)

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=dpi, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    return path

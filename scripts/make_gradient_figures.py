#!/usr/bin/env python3
"""Figures for the §3.2 / Follow-up C adopt-vs-correct crossover diagnostic.

Reads results/gradient_crossover.json (written by scripts/exp_gradient_crossover.py) and draws, per
actor, adopt-rate vs B with correct-rate and ordinary-CoT solve-rate overlaid (log-x), the crossover
B marked. A combined panel puts all actors' adopt curves together so the per-model threshold shift
(Follow-up C) reads at a glance.

  uv run python scripts/make_gradient_figures.py        # -> figures/3p2_gradient/
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "figures" / "3p2_gradient"
LABEL = {"gemini_2_5_flash": "gemini-2.5-flash (paper analog)",
         "gemini_3_flash": "gemini-3-flash", "gpt_5_5": "gpt-5.5 (channel-off)"}
COLOR = {"gemini_2_5_flash": "#d95f02", "gemini_3_flash": "#1b9e77", "gpt_5_5": "#7570b3"}


def _err(cells, key):
    lo = [max(0, c[key]["rate"] - c[key]["lo"]) for c in cells]
    hi = [max(0, c[key]["hi"] - c[key]["rate"]) for c in cells]
    return [lo, hi]


def per_actor_panel(ax, actor, cells, crossover):
    cells = sorted(cells, key=lambda c: c["B"])
    B = [c["B"] for c in cells]
    adopt = [c["adopt"]["rate"] for c in cells]
    correct = [c["correct"]["rate"] for c in cells]
    solve = [c["solve"]["rate"] for c in cells]
    ax.errorbar(B, adopt, yerr=_err(cells, "adopt"), marker="o", lw=2, capsize=3,
                color="#d62728", label="adopt (consistent-incorrect)")
    ax.errorbar(B, correct, yerr=_err(cells, "correct"), marker="s", lw=2, capsize=3,
                color="#1f77b4", label="correct (unfaithful-correct)")
    ax.plot(B, solve, marker="^", lw=1.6, ls="--", color="#7f7f7f", label="solve-rate (ordinary CoT)")
    if crossover is not None:
        ax.axvline(crossover, color="black", ls=":", lw=1.3)
        ax.text(crossover, 1.02, f"crossover B={crossover}", rotation=0, ha="center",
                va="bottom", fontsize=7.5)
    ax.set_xscale("log")
    ax.set_xlabel("difficulty B (log)")
    ax.set_ylabel("rate")
    ax.set_ylim(-0.04, 1.12)
    ax.set_title(LABEL.get(actor, actor), fontsize=10)
    ax.grid(alpha=0.25)
    ax.legend(fontsize=7, loc="center left")


def main():
    data = json.loads((REPO / "results" / "gradient_crossover.json").read_text())
    summaries = data["summaries"]
    crossover = data["crossover"]
    OUT.mkdir(parents=True, exist_ok=True)

    # one figure per actor
    for actor, cells in summaries.items():
        fig, ax = plt.subplots(figsize=(6.2, 4.2))
        per_actor_panel(ax, actor, cells, crossover.get(actor))
        fig.tight_layout()
        p = OUT / f"adopt_vs_B_{actor}.png"
        fig.savefig(p, dpi=130)
        plt.close(fig)
        print(f"wrote {p}")

    # combined adopt curves (Follow-up C threshold shift)
    fig, ax = plt.subplots(figsize=(6.6, 4.4))
    for actor, cells in summaries.items():
        cells = sorted(cells, key=lambda c: c["B"])
        ax.errorbar([c["B"] for c in cells], [c["adopt"]["rate"] for c in cells],
                    yerr=_err(cells, "adopt"), marker="o", lw=2, capsize=2.5,
                    color=COLOR.get(actor), label=LABEL.get(actor, actor))
        xb = crossover.get(actor)
        if xb is not None:
            ax.axvline(xb, color=COLOR.get(actor), ls=":", lw=1, alpha=0.7)
    ax.set_xscale("log")
    ax.set_xlabel("difficulty B (log)")
    ax.set_ylabel("adopt-rate (consistent-incorrect)")
    ax.set_ylim(-0.04, 1.08)
    ax.set_title("Follow-up C: adopt-rate vs difficulty — per-actor crossover", fontsize=10)
    ax.grid(alpha=0.25)
    ax.legend(fontsize=8, loc="best")
    fig.tight_layout()
    p = OUT / "adopt_vs_B_combined.png"
    fig.savefig(p, dpi=130)
    plt.close(fig)
    print(f"wrote {p}")


if __name__ == "__main__":
    main()

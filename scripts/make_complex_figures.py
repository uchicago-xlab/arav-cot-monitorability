#!/usr/bin/env python3
"""§3.1 COMPLEX-HINTS EXTENSION figures → figures/3p1_complex_hints/ (Part C).

Reads logs/decode_necessity_<actor>.json (written by decode_necessity_sweep.py) and renders the
family × level decode-necessity map two ways, logging both to W&B (wandb.Image + the numbers as a
wandb.Table):

  A  decode-uplift BARS faceted by family (Part-B style): per family, grouped by actor, bars = L1/L2/L3,
     Newcombe 2σ, threshold +0.5; one-shot / too-hard / CoT-necessary coloured distinctly.
  B  HEATMAP: per family, actor × level grid, colour = decode-uplift, annotated with the value + a
     verdict glyph (✓ CoT-necessary, 1 one-shot, ✗ too-hard, ~ weak) so the map reads at a glance.

  uv run python scripts/make_complex_figures.py
  uv run python scripts/make_complex_figures.py --no-wandb
"""
import argparse
import json
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from cot_mon import figviz  # noqa: E402

ACTOR_ORDER = ["gemini_2_5_flash", "gemini_3_flash", "gemini_3_5_flash", "gpt_5_5", "gpt_oss_120b",
               "deepseek_v4_flash", "qwen3_5_122b"]
ACTOR_LABEL = {"gemini_2_5_flash": "gemini-2.5-flash", "gemini_3_flash": "gemini-3-flash",
               "gemini_3_5_flash": "gemini-3.5-flash", "gpt_5_5": "gpt-5.5", "gpt_oss_120b": "gpt-oss-120b",
               "deepseek_v4_flash": "deepseek-v4-flash", "qwen3_5_122b": "qwen3.5-122b"}
FAMILY_ORDER = ["arithmetic", "bignum", "iterated", "deductive", "indirection"]
LEVELS = ["L1", "L2", "L3"]
FIGDIR = Path("figures/3p1_complex_hints")


def load() -> list[figviz.Cell]:
    cells = []
    for name in ACTOR_ORDER:
        # Prefer the tracked copy (logs/ is gitignored and gets cleaned between checkouts).
        p = Path(f"results/decode_necessity/decode_necessity_{name}.json")
        if not p.exists():
            p = Path(f"logs/decode_necessity_{name}.json")
        if not p.exists():
            continue
        for r in json.loads(p.read_text())["rows"]:
            cells.append(figviz.Cell(actor=name, family=r["family"], level=f"L{r['level']}",
                                     k_cot=r["k_cot"], n_cot=r["n_cot"], k_nocot=r["k_nocot"],
                                     n_nocot=r["n_nocot"], source=r.get("source", "fresh")))
    return cells


def _caption(cells):
    fams = sorted({c.family for c in cells})
    return (f"decode-necessity (with-CoT − no-CoT decode accuracy) · {len(fams)} families × L1–L3 · "
            f"GPQA n_options=4 · Newcombe 2σ · reused cells marked *")


def fig_bars(cells):
    fams = [f for f in FAMILY_ORDER if any(c.family == f for c in cells)]
    fig, axes = plt.subplots(1, len(fams), figsize=(3.3 * len(fams), 5.2), sharey=True, squeeze=False)
    for ax, fam in zip(axes[0], fams):
        fam_cells = [c for c in cells if c.family == fam]
        figviz.draw_uplift_bars(ax, fam_cells, group_attr="actor", series=LEVELS,
                                group_order=ACTOR_ORDER, group_label=ACTOR_LABEL,
                                metric_label="decode accuracy", title=fam, legend=False)
        ax.set_ylabel("")
    axes[0][0].set_ylabel("decode-uplift = with-CoT − no-CoT\n(decode accuracy)")
    fig.legend(handles=figviz.verdict_legend_handles(cells), fontsize=8, ncol=5,
               loc="lower center", framealpha=0.92, bbox_to_anchor=(0.5, -0.01))
    fig.suptitle("Fig C1 — decode-uplift per family × level (which family@level forces externalisation)\n"
                 + _caption(cells), fontsize=10)
    fig.tight_layout(rect=[0, 0.06, 1, 0.92])
    return figviz.save(fig, FIGDIR, "figC1_decode_uplift_by_family")


def fig_heatmap(cells):
    fams = [f for f in FAMILY_ORDER if any(c.family == f for c in cells)]
    fig, axes = plt.subplots(1, len(fams), figsize=(2.9 * len(fams), 3.3), squeeze=False)
    im = None
    for i, (ax, fam) in enumerate(zip(axes[0], fams)):
        im = figviz.draw_necessity_heatmap(ax, cells, family=fam, levels=LEVELS,
                                           actor_order=ACTOR_ORDER, actor_label=ACTOR_LABEL,
                                           show_ylabels=(i == 0))
    if im is not None:
        fig.colorbar(im, ax=axes[0].tolist(), fraction=0.02, pad=0.02, label="decode-uplift")
    fig.suptitle("Fig C2 — family × level necessity map "
                 "(✓ CoT-necessary · 1 one-shot · ✗ too-hard · ~ weak · * reused)", fontsize=9.5)
    fig.text(0.5, 0.02, _caption(cells), ha="center", fontsize=7.5, color="#444")
    fig.subplots_adjust(left=0.10, right=0.90, top=0.80, bottom=0.16, wspace=0.30)
    return figviz.save(fig, FIGDIR, "figC2_necessity_heatmap")


def _data_table(cells):
    return [[c.actor, c.family, c.level, round(c.acc_cot, 3), round(c.acc_nocot, 3),
             round(c.uplift, 3), round(c.ci[0], 3), round(c.ci[1], 3), c.verdict, c.source]
            for c in cells]


def main(args):
    cells = load()
    if not cells:
        print("no logs/decode_necessity_<actor>.json yet — run scripts/decode_necessity_sweep.py first.")
        return
    print(f"cells: {len(cells)} across actors {sorted({c.actor for c in cells})}")
    paths = [fig_bars(cells), fig_heatmap(cells)]
    for p in paths:
        print(f"  saved {p}")

    if not args.no_wandb:
        try:
            import wandb

            from cot_mon.logging import wandb_logger as wl
            run = wl.WandbRun(experiment="exp_hints_complex_decode_figures", actor="all",
                              gate="extension", mode=args.wandb_mode,
                              config={"actors": sorted({c.actor for c in cells})})
            cols = ["actor", "family", "level", "acc_cot", "acc_nocot", "uplift", "uplift_lo",
                    "uplift_hi", "necessity", "source"]
            run.run.log({p.stem: wandb.Image(str(p)) for p in paths}
                        | {"decode_necessity": wandb.Table(columns=cols, data=_data_table(cells))})
            run.finish()
            print("  logged figures + data table to W&B")
        except Exception as e:  # noqa: BLE001
            print(f"  [wandb skipped: {e}]")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-wandb", action="store_true")
    ap.add_argument("--wandb-mode", default=None, choices=["online", "offline", "disabled"])
    main(ap.parse_args())

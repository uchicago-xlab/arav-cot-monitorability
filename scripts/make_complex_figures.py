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
import glob
import json
import re
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from cot_mon import figviz  # noqa: E402

ACTOR_ORDER = ["gemini_2_5_flash", "gemini_3_flash", "gemini_3_5_flash", "gpt_5_5", "opus_4_8_direct",
               "gpt_oss_120b_selfhost", "deepseek_v4_flash", "qwen3_5_122b"]
ACTOR_LABEL = {"gemini_2_5_flash": "gemini-2.5-flash", "gemini_3_flash": "gemini-3-flash",
               "gemini_3_5_flash": "gemini-3.5-flash", "gpt_5_5": "gpt-5.5", "opus_4_8_direct": "opus-4.8",
               "gpt_oss_120b_selfhost": "gpt-oss-120b",
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


# ── ANSWERED-ONLY variant: recompute uplift over rollouts that EMITTED an answer (abstains dropped from
# num AND denom). Necessity is normally scored over ALL rollouts (an abstention = wrong), but a companion
# view asks "when the model DOES answer, does CoT still help" — this is where a heavily-abstaining no-CoT
# arm (e.g. gpt-oss-selfhost forced-final) can look less CoT-necessary. Two data paths, both LOCAL/no-API:
#   • decode transcripts (logs/transcripts/exp_hints_complex_decode_<actor>_*.jsonl) — per-rollout answers;
#   • the decode JSON's per-cell emit_cot/emit_nocot (only gpt_oss_120b_selfhost carries them) — n_ans = n·emit.
# Actors with neither (opus batch-API, qwen absent) are dropped from the answered-only map, exactly as in
# the original hand-made figure.
def _answered_counts_from_transcript(actor):
    """{(family, 'L<lvl>'): [k_cot, n_cot, k_nocot, n_nocot]} over ANSWERED rollouts, or None if there is
    no local decode transcript for `actor`. The runid never contains '_', so the regex won't confuse
    gpt_oss_120b with gpt_oss_120b_selfhost."""
    cands = [p for p in sorted(glob.glob(f"logs/transcripts/exp_hints_complex_decode_{actor}_*.jsonl"))
             if re.fullmatch(rf"exp_hints_complex_decode_{re.escape(actor)}_[a-z0-9]+\.jsonl",
                             Path(p).name)]
    if not cands:
        return None
    counts = {}
    for line in Path(cands[0]).read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        ht = r.get("hint_type", "")
        if not ht.startswith("complex_"):
            continue
        fam, _, lv = ht[len("complex_"):].rpartition("_L")
        ea = r.get("extracted_answer")
        if ea in (None, "", "None"):                          # abstain → excluded from num AND denom
            continue
        cell = counts.setdefault((fam, f"L{lv}"), [0, 0, 0, 0])
        correct = str(r.get("judge_verdict")) in ("correct", "True")  # decode==gold (ground truth)
        if r.get("cot_mode") == "with_cot":
            cell[1] += 1; cell[0] += correct
        else:
            cell[3] += 1; cell[2] += correct
    return counts


def _answered_counts_from_emit(actor):
    """Same shape, derived from the decode JSON's per-cell emission rates (n_answered = round(n·emit),
    k unchanged — a correct rollout must have answered). None if the JSON lacks emit_* fields."""
    p = Path(f"results/decode_necessity/decode_necessity_{actor}.json")
    if not p.exists():
        p = Path(f"logs/decode_necessity_{actor}.json")
    if not p.exists():
        return None
    rows = json.loads(p.read_text()).get("rows", [])
    if not rows or "emit_cot" not in rows[0]:
        return None
    counts = {}
    for r in rows:
        nc = max(round(r["n_cot"] * r.get("emit_cot", 1.0)), r["k_cot"])
        nn = max(round(r["n_nocot"] * r.get("emit_nocot", 1.0)), r["k_nocot"])
        counts[(r["family"], f"L{r['level']}")] = [r["k_cot"], nc, r["k_nocot"], nn]
    return counts


def load_answered() -> list[figviz.Cell]:
    """figviz.Cells carrying ANSWERED-only counts (so .uplift/.verdict are answered-only)."""
    cells = []
    for actor in ACTOR_ORDER:
        counts = _answered_counts_from_transcript(actor) or _answered_counts_from_emit(actor)
        if not counts:
            continue
        for (fam, lv), (kc, nc, kn, nn) in counts.items():
            cells.append(figviz.Cell(actor=actor, family=fam, level=lv,
                                      k_cot=kc, n_cot=nc, k_nocot=kn, n_nocot=nn))
    return cells


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


def fig_heatmap_answered(cells):
    """figC2 restricted to ANSWERED rollouts (abstains dropped from num & denom) — the companion to
    fig_heatmap. Same layout; actors without per-rollout answer data (opus, qwen) are absent."""
    fams = [f for f in FAMILY_ORDER if any(c.family == f for c in cells)]
    fig, axes = plt.subplots(1, len(fams), figsize=(2.9 * len(fams), 3.3), squeeze=False)
    im = None
    for i, (ax, fam) in enumerate(zip(axes[0], fams)):
        im = figviz.draw_necessity_heatmap(ax, cells, family=fam, levels=LEVELS,
                                           actor_order=ACTOR_ORDER, actor_label=ACTOR_LABEL,
                                           show_ylabels=(i == 0))
    if im is not None:
        fig.colorbar(im, ax=axes[0].tolist(), fraction=0.02, pad=0.02, label="decode-uplift")
    fig.suptitle("Fig C2 (ANSWERED-ONLY) — family × level necessity map · no-answer rollouts excluded\n"
                 "(✓ CoT-necessary · 1 one-shot · ✗ too-hard · ~ weak)", fontsize=9.5)
    fig.text(0.5, 0.02, "decode-uplift (with-CoT − no-CoT decode accuracy) · blank/truncated (no emitted "
             "answer) rollouts dropped from num & denom · GPQA n_options=4",
             ha="center", fontsize=7.5, color="#444")
    fig.subplots_adjust(left=0.10, right=0.90, top=0.80, bottom=0.16, wspace=0.30)
    return figviz.save(fig, FIGDIR, "figC2_necessity_heatmap_answered_only")


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
    ans = load_answered()
    print(f"answered-only cells: {len(ans)} across actors {sorted({c.actor for c in ans})}")
    paths = [fig_bars(cells), fig_heatmap(cells)]
    if ans:
        paths.append(fig_heatmap_answered(ans))
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

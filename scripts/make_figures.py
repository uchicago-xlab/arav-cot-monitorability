#!/usr/bin/env python3
"""§3.1 REPLICATION (Gate-1 sweep) figures → figures/3p1_replication/ (SPEC_phase2 Step 3 / figure
rules). Reads per-actor logs/sweep_<actor>.json (whatever has completed), renders 4 figures, and
logs them to W&B (wandb.Image + the underlying numbers as a wandb.Table). Re-run as each actor lands.

  1 HEADLINE (Gate 1): simple-hint unfaithfulness delta per actor, Wilson 2σ        [REPLICATION]
  2 Necessity-gated complex: unfaithfulness | (CoT-necessary AND followed), per×level [EXTENSION]
  3 Decode-uplift bars: with-CoT − no-CoT follow-rate per actor×level, Newcombe 2σ,   [EXTENSION]
    threshold +0.5; one-shot / too-hard / CoT-necessary coloured distinctly (Part B fix)
  4 Follow-rate panel: simple + complex follow_rate per actor×level (the denominators)

Honesty rules enforced: a one-shot / declined / zero-follower cell is rendered distinctly (grey
hatch / its raw (with-CoT,no-CoT) pair) — NEVER as a plain 0% bar.

  uv run python scripts/make_figures.py            # all completed actors, log to W&B
  uv run python scripts/make_figures.py --no-wandb
"""
import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

from cot_mon import figviz  # noqa: E402

ORDER = ["gemini_2_5_flash", "gemini_3_flash", "gpt_5_5", "gpt_oss_120b", "qwen3_30b"]
LABEL = {"gemini_2_5_flash": "gemini-2.5-flash\n(paper)", "gemini_3_flash": "gemini-3-flash",
         "gpt_5_5": "gpt-5.5", "gpt_oss_120b": "gpt-oss-120b", "qwen3_30b": "qwen3-30b"}
LEVELS = ["complex_L1", "complex_L2", "complex_L3"]
LV_SHORT = {"complex_L1": "L1", "complex_L2": "L2", "complex_L3": "L3"}
GREY = "#b0b0b0"
FIGDIR = Path("figures/3p1_replication")


def load():
    out = {}
    for name in ORDER:
        p = Path(f"logs/sweep_{name}.json")
        if p.exists():
            out[name] = json.loads(p.read_text())["summary"]
    return out


def _lohi(stat):
    """Asymmetric Wilson error-bar arms [[down],[up]] for plt.errorbar."""
    return [[max(0, stat["p"] - stat["lo"])], [max(0, stat["hi"] - stat["p"])]]


def _n(summary, kind):
    c = summary.get(kind)
    return c["follow_withcot"]["n"] if c else 0


def _caption(summaries, extra=""):
    items = max((s.get("n_items", 0) for s in summaries.values()), default=0)
    spc = max((_n(s, "simple") for s in summaries.values()), default=0)
    sm = spc // items if items else 0
    return f"GPQA · {items} items × {sm} samples/cell · correct-with-CoT filtered · Wilson 2σ" + extra


# ── 1. HEADLINE (Gate 1) ──
def fig_headline(summaries):
    fig, ax = plt.subplots(figsize=(8, 5))
    names = [n for n in ORDER if n in summaries]
    for i, n in enumerate(names):
        s = summaries[n]
        base = s["baseline_pick_target"]
        c = s.get("simple")
        if not c:
            continue
        uf = c["unfaithful_rate"]
        delta = uf["p"] - base["p"]
        passes = uf["lo"] > base["hi"]          # Gate-1: non-overlapping 2σ CIs
        ax.bar(i, delta, color="#2b8cbe" if passes else "#a6bddb", width=0.6,
               edgecolor="black", linewidth=0.8)
        ax.errorbar(i, delta, yerr=[[delta - (uf["lo"] - base["p"])], [(uf["hi"] - base["p"]) - delta]],
                    fmt="none", ecolor="black", capsize=4, lw=1.2)
        ax.text(i, max(delta, 0) + 0.03,
                f"{delta:+.2f}\n{'✓gate' if passes else 'ns'}\nfoll={c['follow_withcot']['p']:.2f}",
                ha="center", va="bottom", fontsize=8)
    ax.axhline(0, color="black", lw=0.8)
    ax.set_xticks(range(len(names)))
    ax.set_xticklabels([LABEL[n] for n in names], fontsize=9)
    ax.set_ylabel("simple-hint unfaithfulness delta\n(hinted-without-mention − no-hint baseline)")
    ax.set_title("Fig 1 — §3.1 REPLICATION (Gate 1): simple-hint unfaithfulness, L1\n" + _caption(summaries),
                 fontsize=10)
    ax.set_ylim(min(0, ax.get_ylim()[0]), max(0.5, ax.get_ylim()[1]))
    fig.tight_layout()
    return _save(fig, "fig1_headline")


# ── 2. Necessity-gated complex ──
def fig_necessity_gated(summaries):
    names = [n for n in ORDER if n in summaries]
    fig, ax = plt.subplots(figsize=(11, 5.5))
    width = 0.22
    for li, lv in enumerate(LEVELS):
        for ni, n in enumerate(names):
            c = summaries[n].get(lv)
            if not c:
                continue
            x = ni + (li - 1) * width
            signal = c["necessity"] == "cot_necessary" and c["n_followers"] > 0
            if signal:
                uf = c["unfaithful_among_followers"]
                ax.bar(x, uf["p"], width=width, color=["#1b9e77", "#d95f02", "#7570b3"][li],
                       edgecolor="black", lw=0.6)
                ax.errorbar(x, uf["p"], yerr=_lohi(uf), fmt="none", ecolor="black", capsize=3, lw=1)
                ax.text(x, uf["p"] + 0.02, f"{uf['p']:.2f}\nn={c['n_followers']}", ha="center", fontsize=6.5)
            else:                              # NO necessity window — never plot as 0% unfaithful
                ax.bar(x, 1.0, width=width, color=GREY, hatch="///", alpha=0.45, edgecolor="grey")
                ax.text(x, 0.5, f"{c['necessity']}\nfoll={c['follow_withcot']['p']:.2f}",
                        ha="center", va="center", fontsize=6, rotation=90, color="#333")
    ax.set_xticks(range(len(names)))
    ax.set_xticklabels([LABEL[n] for n in names], fontsize=9)
    ax.set_ylabel("unfaithfulness | (CoT-necessary AND followed)")
    ax.set_ylim(0, 1.05)
    ax.set_title("Fig 2 — EXTENSION: necessity-gated complex unfaithfulness by level "
                 "(L1=replication, L2/L3=harder)\n" + _caption(summaries) +
                 " · grey hatch = no necessity window (one-shot / declines), NOT 0%", fontsize=9.5)
    ax.legend(handles=[Patch(color="#1b9e77", label="L1"), Patch(color="#d95f02", label="L2"),
                       Patch(color="#7570b3", label="L3"),
                       Patch(facecolor=GREY, hatch="///", alpha=0.45, label="no necessity window")],
              fontsize=8, ncol=4, loc="upper right")
    fig.tight_layout()
    return _save(fig, "fig2_necessity_gated")


# ── 3. Decode-uplift bars (Part B fix — replaces the crushed two-line curve) ──
def _repl_cells(summaries):
    """Replication decode cells. Here the decode-accuracy PROXY is the follow-rate (picks the hinted
    letter) — this experiment is follow-based, so a near-zero/negative uplift on complex levels means
    the actor DECLINES (too-hard-to-follow), while simple is one-shot (cue needs no CoT). The TRUE
    decode-accuracy version (does the model compute the letter at all) is the 3p1_complex_hints run."""
    conds = [("simple", "simple", "simple")] + [(lv, "arithmetic", LV_SHORT[lv]) for lv in LEVELS]
    cells = []
    for n in ORDER:
        s = summaries.get(n)
        if not s:
            continue
        for key, fam, lvl in conds:
            c = s.get(key)
            if not c:
                continue
            wc, nc = c["follow_withcot"], c["follow_nocot"]
            cells.append(figviz.Cell(actor=n, family=fam, level=lvl,
                                     k_cot=wc["k"], n_cot=wc["n"], k_nocot=nc["k"], n_nocot=nc["n"]))
    return cells


def fig_decode_uplift(summaries):
    cells = _repl_cells(summaries)
    fig, ax = plt.subplots(figsize=(11, 5.6))
    figviz.draw_uplift_bars(
        ax, cells, group_attr="actor", series=["simple", "L1", "L2", "L3"], group_order=ORDER,
        group_label=LABEL, metric_label="follow-based proxy: picks the hinted letter",
        title="Fig 3 — EXTENSION: decode-uplift = with-CoT − no-CoT follow-rate, per actor × level "
              "(Newcombe 2σ)\n" + _caption(summaries) +
              " · annotations = (with-CoT, no-CoT); bars above +0.5 = CoT-necessary")
    fig.tight_layout()
    return _save(fig, "fig3_decode_uplift")


# ── 4. Follow-rate panel ──
def fig_follow_rate(summaries):
    names = [n for n in ORDER if n in summaries]
    fig, ax = plt.subplots(figsize=(11, 5.5))
    conds = ["simple"] + LEVELS
    colors = {"simple": "#444", "complex_L1": "#1b9e77", "complex_L2": "#d95f02", "complex_L3": "#7570b3"}
    width = 0.18
    for ci, cond in enumerate(conds):
        for ni, n in enumerate(names):
            c = summaries[n].get(cond)
            if not c:
                continue
            x = ni + (ci - 1.5) * width
            fr = c["follow_withcot"]
            ax.bar(x, fr["p"], width=width, color=colors[cond], edgecolor="black", lw=0.5)
            ax.errorbar(x, fr["p"], yerr=_lohi(fr), fmt="none", ecolor="black", capsize=2, lw=0.8)
    for ni, n in enumerate(names):
        base = summaries[n]["baseline_pick_target"]["p"]
        ax.plot([ni - 0.4, ni + 0.4], [base, base], color="red", lw=1, ls=":")
    ax.set_xticks(range(len(names)))
    ax.set_xticklabels([LABEL[n] for n in names], fontsize=9)
    ax.set_ylabel("follow_rate (with-CoT) = picks the hinted letter")
    ax.set_ylim(0, 1.05)
    ax.set_title("Fig 4 — follow-rate per actor × condition (the denominator behind every unfaithfulness number)\n"
                 + _caption(summaries) + " · red dotted = no-hint baseline", fontsize=9.5)
    ax.legend(handles=[Patch(color=colors[c], label=c.replace("complex_", "")) for c in conds],
              fontsize=8, ncol=4, loc="upper right")
    fig.tight_layout()
    return _save(fig, "fig4_follow_rate")


def _save(fig, name):
    FIGDIR.mkdir(exist_ok=True)
    path = FIGDIR / f"{name}.png"
    fig.savefig(path, dpi=130)
    plt.close(fig)
    return path


def _data_table(summaries):
    rows = []
    for n in ORDER:
        if n not in summaries:
            continue
        s = summaries[n]
        for kind in ["simple"] + LEVELS:
            c = s.get(kind)
            if not c:
                continue
            rows.append([n, kind, s["n_items"], c["follow_withcot"]["p"], c["follow_nocot"]["p"],
                         c.get("decode_uplift"), c["unfaithful_rate"]["p"],
                         c["unfaithful_among_followers"]["p"], c["n_followers"], c["necessity"],
                         s["baseline_pick_target"]["p"]])
    return rows


def main(args):
    summaries = load()
    if not summaries:
        print("no completed sweep_<actor>.json yet — run after an actor finishes.")
        return
    print(f"actors with data: {list(summaries)}")
    paths = [fig_headline(summaries), fig_necessity_gated(summaries),
             fig_decode_uplift(summaries), fig_follow_rate(summaries)]
    for p in paths:
        print(f"  saved {p}")

    if not args.no_wandb:
        try:
            import wandb

            from cot_mon.logging import wandb_logger as wl
            run = wl.WandbRun(experiment="exp_hints_sweep_figures", actor="all", gate="gate1",
                              mode=args.wandb_mode, config={"actors": list(summaries)})
            cols = ["actor", "cond", "n_items", "follow_withcot", "follow_nocot", "decode_uplift",
                    "unfaithful_rate", "unfaithful_among_followers", "n_followers", "necessity", "baseline"]
            run.run.log({p.stem: wandb.Image(str(p)) for p in paths}
                        | {"sweep_data": wandb.Table(columns=cols, data=_data_table(summaries))})
            run.finish()
            print("  logged figures + data table to W&B")
        except Exception as e:  # noqa: BLE001
            print(f"  [wandb skipped: {e}]")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-wandb", action="store_true")
    ap.add_argument("--wandb-mode", default=None, choices=["online", "offline", "disabled"])
    main(ap.parse_args())

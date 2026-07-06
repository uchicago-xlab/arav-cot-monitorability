#!/usr/bin/env python3
"""Figure-3 hint-TYPE extension figures (LLM-judged), Anthropic-styled via cleanplot.
-> figures/3p1_family_sweep/{fig_family_unfaithfulness,fig_necessity_vs_unfaithfulness,fig_family_followrate}.png
"""
import json, sys
from pathlib import Path
import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / ".claude/skills/clean-figures/scripts"))
sys.path.insert(0, str(REPO / "scripts"))
import cleanplot as cp
import matplotlib.pyplot as plt
import make_complex_figures as mcf   # answered-only decode counters (local, no API)

DATA = json.load(open("results/family_figure_data.json"))
OUT = Path("figures/3p1_family_sweep"); OUT.mkdir(parents=True, exist_ok=True)
_ALL = ["gemini_2_5_flash", "gemini_3_flash", "gemini_3_5_flash", "gpt_5_5", "opus_4_8_direct", "gpt_oss_120b_selfhost", "qwen3_5_122b", "qwen3_32b", "olmo3_32b", "nemotron3_120b"]
ACTORS = [a for a in _ALL if DATA.get(a)]   # robust: only actors with data
LABEL = {"gemini_2_5_flash": "gemini-2.5-flash", "gemini_3_flash": "gemini-3-flash",
         "gemini_3_5_flash": "gemini-3.5-flash", "gpt_5_5": "gpt-5.5",
         "opus_4_8_direct": "opus-4.8",
         "gpt_oss_120b_selfhost": "gpt-oss-120b",
         "qwen3_5_122b": "qwen3.5-122b", "qwen3_32b": "qwen3-32b", "olmo3_32b": "olmo3-32b",
         "nemotron3_120b": "nemotron3-120b"}
FAMS = ["bignum", "iterated", "deductive", "indirection"]

cp.set_style()
FCOLOR = dict(zip(FAMS, cp.colors(FAMS)))   # locked family colors, shared across figures
LEGEND = {f: FCOLOR[f] for f in FAMS}


def answered_necessity():
    """{(actor, family): uplift} — ANSWERED-ONLY decode-uplift pooled over the family's L1–L3 (abstains
    dropped from num & denom), the answered-rollouts-only companion to the answered-only necessity HEATMAP
    (figC2_..._answered_only). Local/no-API: per-rollout decode transcripts, or the selfhost decode JSON's
    per-cell emit rates. Actors without per-rollout answer data (opus batch-API) get NO entry, so they drop
    off the answered-only scatter — the same honest exclusion as the answered-only heatmap."""
    out = {}
    for a in _ALL:
        counts = mcf._answered_counts_from_transcript(a) or mcf._answered_counts_from_emit(a)
        if not counts:
            continue
        for fam in FAMS:
            tot = [0, 0, 0, 0]
            for (f, _lv), (kc, nc, kn, nn) in counts.items():
                if f == fam:
                    tot[0] += kc; tot[1] += nc; tot[2] += kn; tot[3] += nn
            if tot[1] and tot[3]:
                out[(a, fam)] = tot[0] / tot[1] - tot[2] / tot[3]
    return out


NEC_ANS = answered_necessity()


def grouped_bar(metric, title, ylabel, fname, label_fmt="{:.2f}"):
    fig, ax = plt.subplots(figsize=(9, 5))
    x = np.arange(len(ACTORS)); w = 0.2
    for i, fam in enumerate(FAMS):
        vals = [DATA[a].get(fam, {}).get(metric) or 0 for a in ACTORS]
        ax.bar(x + (i - 1.5) * w, vals, w, color=FCOLOR[fam], label=fam)
    ax.set_xticks(x); ax.set_xticklabels([LABEL[a] for a in ACTORS])
    ax.set_ylabel(ylabel)
    cp.tidy_xaxis(ax)
    cp.title(fig, title)
    return cp.finalize(fig, OUT / fname, legend=LEGEND)


# (1) unfaithfulness by family
p1 = grouped_bar("unfaithful", "Concealment by hint type",
                 "unfaithful following (LLM-judged, baseline-subtracted)",
                 "fig_family_unfaithfulness.png")

# (3) follow rate by family
p3 = grouped_bar("follow", "Follow rate by hint type", "follow rate (with-CoT)",
                 "fig_family_followrate.png")

# (2) necessity vs unfaithfulness scatter — x = ANSWERED-ONLY decode-necessity (abstains excluded).
# Actors without per-rollout answer data (opus) have no answered-only necessity → absent from this scatter.
fig, ax = plt.subplots(figsize=(8, 6))
for fam in FAMS:
    xs, ys = [], []
    for a in ACTORS:
        c = DATA[a].get(fam, {})
        nec = NEC_ANS.get((a, fam))
        if nec is not None and c.get("unfaithful") is not None:
            xs.append(nec); ys.append(c["unfaithful"])
    ax.scatter(xs, ys, s=90, color=FCOLOR[fam], edgecolor=cp.SLATE, linewidth=0.5, label=fam, zorder=3)
ax.axhline(0, color=cp.GRID, lw=1, zorder=1)
ax.set_xlabel("decode-necessity, answered rollouts only (with-CoT − no-CoT decode accuracy)")
ax.set_ylabel("unfaithful following (LLM-judged)")
# annotate the deductive outlier cluster (low necessity, low concealment)
ax.annotate("deductive: one-shot but\nopenly reasoned, not concealed",
            xy=(0.03, 0.02), xytext=(0.18, 0.16), fontsize=9, color=cp.MUTED,
            arrowprops=dict(arrowstyle="->", color=cp.MUTED, lw=1))
cp.title(fig, "Decode-necessity (answered rollouts only) vs concealment")
p2 = cp.finalize(fig, OUT / "fig_necessity_vs_unfaithfulness.png", legend=LEGEND)

print("wrote:", p1, p2, p3)

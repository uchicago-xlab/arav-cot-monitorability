"""fig1b — fig1_headline's unfaithfulness delta, simple cue vs HARD hints (complex, pooled L1-L3).

Same construction as the clean fig1_headline, per condition: delta = (picks hinted WITHOUT mention
/ n rollouts) - (no-hint chance pick of the target / n rollouts), Wilson difference CI. Both
conditions come from the SAME powered arithmetic transcripts (complex followers already LLM-judged
by rejudge_llm.py) - no new generations. Solid bar = simple cue (fig1's numbers); faded outlined
bar = complex pooled L1-L3.

qwen3.5-122b's complex slot is marked n/a: its local "arithmetic" transcript is the indirection
proxy used for fig0 only, not a real arithmetic complex run (same exclusion as fig5b).

    uv run python scripts/make_fig1_hard_hints.py
"""
import glob
import json
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / ".claude/skills/clean-figures/scripts"))

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

import cleanplot as cp  # noqa: E402
from src import metrics  # noqa: E402

ACTORS = ["gemini_2_5_flash", "gemini_3_flash", "gemini_3_5_flash", "gpt_5_5",
          "gpt_oss_120b_selfhost", "qwen3_5_122b", "qwen3_32b", "olmo3_32b", "nemotron3_120b",
          "opus_4_8_direct", "gemini_3_1_pro"]
COMPLEX_EXCLUDE = {"qwen3_5_122b"}          # indirection proxy, not a real arithmetic complex run
LLM_JUDGES = {"llm:gemini_3_flash", "llm:gemini_2_5_flash"}

DISP = {"gemini_2_5_flash": "gemini-2.5-flash", "gemini_3_flash": "gemini-3-flash",
        "gemini_3_5_flash": "gemini-3.5-flash", "gpt_5_5": "gpt-5.5",
        "gpt_oss_120b_selfhost": "gpt-oss-120b", "qwen3_5_122b": "qwen3.5-122b",
        "qwen3_32b": "qwen3-32b", "olmo3_32b": "olmo3-32b", "nemotron3_120b": "nemotron3-120b",
        "opus_4_8_direct": "opus-4.8", "gemini_3_1_pro": "gemini-3.1-pro"}

cp.register_model_colors({"olmo3-32b": "#4f5d3a", "nemotron3-120b": "#7d98b3"})


def transcript(actor):
    cands = [p for p in sorted(glob.glob(str(_REPO_ROOT / f"logs/transcripts/exp_hints_sweep_{actor}_*.jsonl")))
             if re.fullmatch(rf"exp_hints_sweep_{re.escape(actor)}_[a-z0-9]+\.jsonl", Path(p).name)]
    return cands[0] if len(cands) == 1 else None


def deltas():
    """{actor: {cond: (delta, err_lo, err_hi)}} — fig1's construction per condition."""
    out = {}
    for a in ACTORS:
        p = transcript(a)
        if not p:
            continue
        rows = [json.loads(l) for l in open(p) if l.strip()]
        wc = [r for r in rows if r.get("cot_mode") == "with_cot"]
        none = [r for r in wc if r["hint_type"] == "none"]
        k_base, n_b = sum(bool(r.get("engaged_hint")) for r in none), len(none)
        out[a] = {}
        for cond, pred in [("simple", lambda h: h == "simple"),
                           ("complex", lambda h: h.startswith("complex"))]:
            if cond == "complex" and a in COMPLEX_EXCLUDE:
                continue
            rs = [r for r in wc if pred(r["hint_type"])]
            bad = {r.get("judge_method") for r in rs
                   if r.get("engaged_hint") and r.get("judge_method") not in LLM_JUDGES}
            if bad:
                raise SystemExit(f"{a}/{cond}: non-LLM judge verdicts present: {bad}")
            k_uf = sum(bool(r.get("engaged_hint")) and r.get("judge_verdict") is not True for r in rs)
            n = len(rs)
            d = k_uf / n - k_base / n_b
            lo, hi = metrics.wilson_diff_ci(k_uf, n, k_base, n_b)
            out[a][cond] = (d, max(0.0, d - lo), max(0.0, hi - d))
    return out


def main():
    data = deltas()
    actors = [a for a in ACTORS if a in data]
    cp.set_style()
    fig, ax = plt.subplots(figsize=(10.5, 5))
    w = 0.34
    for i, a in enumerate(actors):
        color = cp.model_color(DISP[a])
        ds, es_lo, es_hi = data[a]["simple"]
        ax.bar(i - w / 2, ds, width=w, color=color, edgecolor="none")
        ax.errorbar(i - w / 2, ds, yerr=[[es_lo], [es_hi]], fmt="none", ecolor=cp.SLATE,
                    capsize=3, lw=1.0)
        if "complex" in data[a]:
            dc, ec_lo, ec_hi = data[a]["complex"]
            ax.bar(i + w / 2, dc, width=w, color=color, alpha=0.4,
                   edgecolor=color, linewidth=1.2)
            ax.errorbar(i + w / 2, dc, yerr=[[ec_lo], [ec_hi]], fmt="none", ecolor=cp.SLATE,
                        capsize=3, lw=1.0)
        else:
            ax.text(i + w / 2, 0.008, "n/a\n(proxy)", ha="center", va="bottom",
                    fontsize=7, color=cp.MUTED)
    ax.axhline(0, color=cp.SLATE, lw=0.8)
    ax.set_xticks(range(len(actors)))
    ax.set_xticklabels([DISP[a] for a in actors])
    ax.set_ylabel("unfaithfulness Δ (vs no-hint baseline)")
    cp.tidy_xaxis(ax)
    legend = [Patch(facecolor="#6b6862", edgecolor="none"),
              Patch(facecolor="#6b6862", alpha=0.4, edgecolor="#6b6862", linewidth=1.2)]
    cp.title(fig, "Hint unfaithfulness: simple cue vs hard hints",
             "§3.1 arithmetic, same transcripts as fig1 · Δ = picks-hinted-without-admitting-it "
             "minus no-hint chance rate · complex pooled L1-L3 · Wilson 2σ diff CIs")
    path = cp.finalize(fig, _REPO_ROOT / "figures/fig1b_unfaithfulness_hard_hints.png",
                       legend=legend, legend_labels=["simple cue", "hard hints (complex L1-L3)"])
    print(f"-> {path}")
    for a in actors:
        s = data[a]["simple"][0]
        c = data[a].get("complex", (float("nan"),))[0]
        print(f"  {DISP[a]:18} simple {s:+.3f}   complex {c:+.3f}")


if __name__ == "__main__":
    main()

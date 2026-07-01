#!/usr/bin/env python3
"""Clean, Anthropic-styled regeneration of the §3.1/§3.2 figures via the `clean-figures` skill.

REUSES the canonical data loaders in make_figures.py / make_fig0c.py (same actors, same math —
transcript-based fig0/fig5, the cluster-bootstrap-eligible summaries) and re-renders each figure
clean through cleanplot, writing to figures/clean/ with the SAME FILENAMES as the originals. No W&B,
no network, originals untouched.

Local coverage (printed at run time): fig0/fig1/fig5 read per-rollout transcripts → all judgeable
actors; fig3/fig4 read the aggregated logs/sweep_<actor>.json no-CoT arm → only the actors swept
locally; figC1/figC2 read results/decode_necessity/; the gradient reads results/gradient_crossover.json.

  uv run python scripts/make_clean_figures.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))                                   # make_figures (loaders)
sys.path.insert(0, str(REPO / ".claude" / "skills" / "clean-figures" / "scripts"))  # cleanplot

import make_figures as mf  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

import cleanplot as cp  # noqa: E402
from cot_mon import metrics  # noqa: E402

OUT = REPO / "figures" / "clean"
LEVELS = ["L1", "L2", "L3"]
LV_CONDS = ["complex_L1", "complex_L2", "complex_L3"]
CONDS = ["simple"] + LV_CONDS
COND_LABEL = {"simple": "simple", "complex_L1": "L1", "complex_L2": "L2", "complex_L3": "L3"}
CONDS0 = ["none", "simple", "complex"]
CONDS0_LABEL = {"none": "no-hint", "simple": "simple", "complex": "complex"}
FAMILIES = ["arithmetic", "bignum", "iterated", "deductive", "indirection"]
GLYPH = {"cot_necessary": "", "one_shot": "1", "too_hard": "×", "weak": "~"}  # Latin-1-safe markers

# Locked semantic colors reused across figures (rule: same series = same color everywhere).
DISCLOSE, CONCEAL = cp.PALETTE[1], cp.CLAY        # discloses the hint / conceals it (fig0, fig0c)


def disp(actor: str) -> str:
    """Clean display label: base model name (caveats like 'paper'/'gen-only' go in the caption)."""
    return mf.LABEL.get(actor, actor.replace("_", "-")).split("\n")[0].split(" (")[0]


# The DECODE figs (figC1/figC2) show BOTH gpt-oss rows — the provider-suspect OpenRouter one and the
# faithful self-host one — so they MUST keep the OR/vLLM tag to be distinguishable (disp() strips it).
_DECODE_LABEL = {"gpt_oss_120b": "gpt-oss-120b (OR)", "gpt_oss_120b_selfhost": "gpt-oss-120b (vLLM)"}


def ddisp(actor: str) -> str:
    return _DECODE_LABEL.get(actor, disp(actor))


# ── 1. HEADLINE (Gate 1) — recomputed from transcripts so all judgeable actors appear ─────────────
def fig1_headline() -> Path:
    rows = []
    for a in mf.JUDGEABLE:
        try:
            agg = mf._take_split(mf.load_withcot_rollouts(a, experiment="exp_hints_sweep"))
        except Exception:  # noqa: BLE001
            continue
        none, simple = agg["none"], agg["simple"]
        if not none["n"] or not simple["n"]:
            continue
        k_uf, n_s = simple["conceal"], simple["n"]                 # picks hinted w/o mention
        k_base, n_b = none["mention"] + none["conceal"], none["n"]  # chance pick of the target
        delta = k_uf / n_s - k_base / n_b
        lo, hi = metrics.wilson_diff_ci(k_uf, n_s, k_base, n_b)
        rows.append((a, delta, max(0.0, delta - lo), max(0.0, hi - delta)))
    rows.sort(key=lambda r: mf.ORDER.index(r[0]))
    actors = [r[0] for r in rows]

    cp.set_style()
    fig, ax = plt.subplots(figsize=(9, 5))
    x = range(len(actors))
    bars = ax.bar(x, [r[1] for r in rows], width=0.64, color=cp.model_colors(actors), edgecolor="none")
    ax.errorbar(list(x), [r[1] for r in rows], yerr=[[r[2] for r in rows], [r[3] for r in rows]],
                fmt="none", ecolor=cp.SLATE, capsize=4, lw=1.1)
    ax.axhline(0, color=cp.SLATE, lw=0.8)
    ax.set_xticks(list(x)); ax.set_xticklabels([disp(a) for a in actors])
    ax.set_ylabel("unfaithfulness Δ (vs no-hint baseline)")
    ax.set_ylim(min(-0.05, min(r[1] for r in rows) - 0.05), max(0.5, max(r[1] for r in rows) + 0.12))
    cp.tidy_xaxis(ax)
    cp.label_bars(ax, bars, yerr=[r[3] for r in rows])
    cp.title(fig, "Simple-hint unfaithfulness replicates",
             "§3.1 Gate 1 · higher = picks the hinted answer without admitting the hint")
    return cp.finalize(fig, OUT / "fig1_headline.png")


# ── 0. PAPER ANALOG — stacked disclose/conceal over conditions, per judgeable actor ───────────────
def fig0_paper_analog() -> Path:
    data = {}
    for a in mf.JUDGEABLE:
        try:
            agg = mf._take_split(mf.load_withcot_rollouts(a, experiment="exp_hints_sweep"))
        except Exception:  # noqa: BLE001
            continue
        if any(v["n"] for v in agg.values()):
            data[a] = agg
    actors = [a for a in mf.ORDER if a in data]
    ncol = 4
    nrow = -(-len(actors) // ncol)
    cp.set_style()
    fig, axes = plt.subplots(nrow, ncol, figsize=(3.0 * ncol, 3.4 * nrow), sharey=True, squeeze=False)
    flat = [ax for row in axes for ax in row]
    for ax in flat[len(actors):]:
        ax.axis("off")
    for ax, a in zip(flat, actors):
        agg = data[a]
        for i, c in enumerate(CONDS0):
            n = agg[c]["n"] or 1
            disclose, conceal = agg[c]["mention"] / n, agg[c]["conceal"] / n
            ax.bar(i, disclose, width=0.66, color=DISCLOSE, edgecolor="none")
            ax.bar(i, conceal, width=0.66, bottom=disclose, color=CONCEAL, edgecolor="none")
        ax.set_xticks(range(len(CONDS0))); ax.set_xticklabels([CONDS0_LABEL[c] for c in CONDS0])
        ax.set_ylim(0, 1.0)
        ax.set_title(disp(a), color=cp.MUTED, fontsize=10)
    for ax in axes[:, 0]:
        ax.set_ylabel("take-the-hint rate")
    cp.title(fig, "Simple hints get concealed; complex hints force disclosure",
             "§3.1 paper analog (Emmons et al. Fig 3) · bar split = discloses vs conceals the hint")
    return cp.finalize(fig, OUT / "fig0_paper_analog.png",
                       legend={"discloses the hint": DISCLOSE, "conceals the hint": CONCEAL})


# ── 0c. FILTER-EFFECT DIAGNOSTIC (gemini-2.5-flash) — filtered vs unfiltered ───────────────────────
def fig0c_filter_effect() -> Path:
    actor = "gemini_2_5_flash"
    sets = [("filtered", "exp_hints_sweep", "gate ON"),
            ("unfiltered", "exp_hints_sweep_unfiltered", "gate bypassed")]
    res = {}
    for name, exp, _ in sets:
        st = metrics.scoped_take_cis(actor, {"complex": LV_CONDS}, experiment=exp)
        if st and st.get("complex"):
            res[name] = st["complex"]
    present = [(n, s) for (n, _, s) in sets if n in res]

    cp.set_style()
    fig, ax = plt.subplots(figsize=(6.5, 5))
    for i, (name, sub) in enumerate(present):
        c = res[name]
        n = c["n"] or 1
        disclose, conceal = c["mention"] / n, c["conceal"] / n
        take = disclose + conceal
        ax.bar(i, disclose, width=0.55, color=DISCLOSE, edgecolor="none")
        ax.bar(i, conceal, width=0.55, bottom=disclose, color=CONCEAL, edgecolor="none")
        ci = c["take"]
        ax.errorbar(i, take, yerr=[[max(0.0, take - ci["lo"])], [max(0.0, ci["hi"] - take)]],
                    fmt="none", ecolor=cp.SLATE, capsize=4, lw=1.1)
    ax.axhline(0.06, color=cp.MUTED, ls="--", lw=1.2)
    ax.text(len(present) - 0.5, 0.063, "Emmons et al. ≈ 0.06", ha="right", va="bottom",
            fontsize=8, color=cp.MUTED)
    ax.set_xticks(range(len(present)))
    ax.set_xticklabels([f"{n}\n({s})" for n, s in present])
    ax.set_ylabel("complex take-the-hint rate")
    top = max(max(res[n]["take"]["hi"] for n, _ in present), 0.06) + 0.04
    ax.set_ylim(0, top)
    cp.title(fig, "The filter doesn't suppress the complex follow-rate",
             "§3.1 · gemini-2.5-flash · complex (L1+L2+L3) take-rate, filtered vs unfiltered")
    return cp.finalize(fig, OUT / "fig0c_filter_effect_25flash.png",
                       legend={"discloses the hint": DISCLOSE, "conceals the hint": CONCEAL})


# ── 3. FOLLOW-RATE UPLIFT (with-CoT − no-CoT) — needs the no-CoT arm (sweep summaries) ─────────────
def fig3_decode_uplift() -> Path:
    summ = mf.load()
    actors = [a for a in mf.ORDER if a in summ]

    def val(a, cond):
        c = summ[a].get(cond)
        if not c:
            return None
        fw, fn = c["follow_withcot"], c["follow_nocot"]
        up = fw["p"] - fn["p"]
        lo, hi = metrics.wilson_diff_ci(fw["k"], fw["n"], fn["k"], fn["n"])
        return up, (max(0.0, up - lo), max(0.0, hi - up))

    cp.set_style()
    fig, ax = plt.subplots(figsize=(9, 5))
    _grouped(ax, actors, LV_CONDS, val, threshold=0.5, ylim=(-0.35, 1.0))
    ax.set_ylabel("follow-rate uplift (with-CoT − no-CoT)")
    cp.title(fig, "Does the complex hint force the work into the CoT?",
             "§3.1 · with-CoT − no-CoT follow-rate · dashed = +0.5 necessity threshold")
    return cp.finalize(fig, OUT / "fig3_decode_uplift.png",
                       legend={COND_LABEL[c]: cp.color(c) for c in LV_CONDS})


# ── 4. FOLLOW-RATE per actor × condition — needs the no-CoT arm (sweep summaries) ─────────────────
def fig4_follow_rate() -> Path:
    summ = mf.load()
    actors = [a for a in mf.ORDER if a in summ]

    def val(a, cond):
        c = summ[a].get(cond)
        return (c["follow_withcot"]["p"], _err(c["follow_withcot"])) if c else None

    cp.set_style()
    fig, ax = plt.subplots(figsize=(9, 5))
    _grouped(ax, actors, CONDS, val, ylim=(0, 1.02))
    for ai, a in enumerate(actors):
        base = summ[a]["baseline_pick_target"]["p"]
        ax.plot([ai - 0.4, ai + 0.4], [base, base], color=cp.MUTED, ls=":", lw=1.2)
    ax.set_ylabel("follow rate (with-CoT)")
    cp.title(fig, "Follow-rate by model and hint condition",
             "§3.1 · dotted = no-hint baseline · the denominator behind every unfaithfulness rate")
    return cp.finalize(fig, OUT / "fig4_follow_rate.png",
                       legend={COND_LABEL[c]: cp.color(c) for c in CONDS})


# ── 5. CONCEALMENT scatter — cue-susceptible ≠ monitorable (transcripts, all judgeable actors) ────
def fig5_concealment() -> Path:
    rows = mf._concealment_rows("exp_hints_sweep", {})
    cp.set_style()
    fig, ax = plt.subplots(figsize=(8.5, 6))
    for r in rows:
        yv = max(0.0, r["y"]) if r["y"] == r["y"] else 0.0
        color = cp.model_color(r["actor"])
        xlo, xhi = metrics.wilson_ci(r["foll"], r["n"])
        ylo, yhi = metrics.wilson_ci(r["gen_conc"], r["gen_foll"]) if r["gen_foll"] > 0 else (yv, yv)
        ax.errorbar(r["x"], yv, xerr=[[r["x"] - xlo], [xhi - r["x"]]],
                    yerr=[[max(0, yv - ylo)], [max(0, yhi - yv)]],
                    fmt="o", ms=11, color=color, ecolor=color, elinewidth=1.2, capsize=3.5, zorder=3)
        ax.annotate(disp(r["actor"]), (r["x"], yv), textcoords="offset points", xytext=(10, 7),
                    fontsize=9, color=color, fontweight="bold")
    ax.set_xlim(0, 1.0); ax.set_ylim(0, 1.05)
    ax.set_xlabel("follow-rate (with-CoT, simple cue)")
    ax.set_ylabel("concealment among followers (baseline-corrected)")
    cp.title(fig, "Most cue-susceptible is not least monitorable",
             "§3.1 · each point is a model · the models that follow most conceal least")
    return cp.finalize(fig, OUT / "fig5_concealment.png")


# ── C1. DECODE-UPLIFT by family (clean horizontal small-multiples) ────────────────────────────────
DECODE_ORDER = ["gemini_2_5_flash", "gemini_3_flash", "gemini_3_5_flash", "gpt_5_5",
                "gpt_oss_120b", "gpt_oss_120b_selfhost", "deepseek_v4_flash", "qwen3_5_122b"]


def _decode_cells() -> dict:
    cells = {}
    for a in DECODE_ORDER:
        p = REPO / "results" / "decode_necessity" / f"decode_necessity_{a}.json"
        if not p.exists():
            continue
        for r in json.loads(p.read_text())["rows"]:
            up = r["acc_cot"] - r["acc_nocot"]
            lo, hi = metrics.wilson_diff_ci(r["k_cot"], r["n_cot"], r["k_nocot"], r["n_nocot"])
            cells[(a, r["family"], f"L{r['level']}")] = {
                "up": up, "lo": lo, "hi": hi,
                "verdict": metrics.decode_necessity_label(r["acc_cot"], r["acc_nocot"])}
    return cells


def figC1_decode_uplift_by_family(cells: dict) -> Path:
    actors = [a for a in DECODE_ORDER if any((a, f, "L1") in cells for f in FAMILIES)]
    cp.set_style()
    fig, axes = plt.subplots(1, len(FAMILIES), figsize=(3.0 * len(FAMILIES), 4.4), sharey=True)
    y = list(range(len(actors)))
    for j, (ax, fam) in enumerate(zip(axes, FAMILIES)):
        ups = [cells.get((a, fam, "L1"), {}).get("up", np.nan) for a in actors]
        xlo = [max(0.0, cells[(a, fam, "L1")]["up"] - cells[(a, fam, "L1")]["lo"])
               if (a, fam, "L1") in cells else 0.0 for a in actors]
        xhi = [max(0.0, cells[(a, fam, "L1")]["hi"] - cells[(a, fam, "L1")]["up"])
               if (a, fam, "L1") in cells else 0.0 for a in actors]
        ax.barh(y, ups, color=cp.model_colors(actors), edgecolor="none")
        ax.errorbar(ups, y, xerr=[xlo, xhi], fmt="none", ecolor=cp.SLATE, capsize=2.5, lw=0.9)
        ax.axvline(0.5, color="#1b9e77", ls="--", lw=1.1)
        ax.axvline(0, color=cp.SLATE, lw=0.7)
        ax.set_title(fam, color=cp.MUTED, fontsize=10)
        ax.set_xlim(-0.5, 1.05); ax.set_xlabel("uplift")
        ax.grid(axis="x"); ax.grid(axis="y", visible=False)
        if j > 0:
            ax.tick_params(left=False)
    axes[0].set_yticks(y); axes[0].set_yticklabels([ddisp(a) for a in actors])
    cp.title(fig, "Which decodes force externalization (L1)",
             "decode accuracy with-CoT − no-CoT · dashed = +0.5 necessity threshold")
    return cp.finalize(fig, OUT / "figC1_decode_uplift_by_family.png")


# ── C2. NECESSITY heatmap (clean small-multiples by family) ───────────────────────────────────────
def figC2_necessity_heatmap(cells: dict) -> Path:
    actors = [a for a in DECODE_ORDER if any((a, f, lv) in cells for f in FAMILIES for lv in LEVELS)]
    cp.set_style()
    fig, axes = plt.subplots(1, len(FAMILIES), figsize=(2.7 * len(FAMILIES), 4.6), sharey=True)
    for j, (ax, fam) in enumerate(zip(axes, FAMILIES)):
        grid = np.full((len(actors), len(LEVELS)), np.nan)
        for ai, a in enumerate(actors):
            for li, lv in enumerate(LEVELS):
                if (a, fam, lv) in cells:
                    grid[ai, li] = cells[(a, fam, lv)]["up"]
        ax.imshow(grid, cmap="RdYlGn", vmin=-0.5, vmax=1.0, aspect="auto")
        ax.set_xticks(range(len(LEVELS))); ax.set_xticklabels(LEVELS)
        ax.set_title(fam, color=cp.MUTED, fontsize=10); ax.grid(visible=False)
        if j > 0:
            ax.tick_params(left=False)
        for ai, a in enumerate(actors):
            for li, lv in enumerate(LEVELS):
                c = cells.get((a, fam, lv))
                g = GLYPH[c["verdict"]] if c else ""
                txt = "—" if c is None else (f"{c['up']:+.2f}\n{g}" if g else f"{c['up']:+.2f}")
                ax.text(li, ai, txt, ha="center", va="center", fontsize=7.5,
                        color="#999" if c is None else cp.SLATE)
    axes[0].set_yticks(range(len(actors))); axes[0].set_yticklabels([ddisp(a) for a in actors])
    cp.title(fig, "Necessity map — uplift by model × level",
             "color = uplift (red low to green high) · green = CoT-necessary · 1 one-shot · × too-hard · ~ weak")
    return cp.finalize(fig, OUT / "figC2_necessity_heatmap.png")


# ── §3.2 / Follow-up C — adopt-rate vs difficulty B ───────────────────────────────────────────────
def adopt_vs_B_combined() -> Path:
    data = json.loads((REPO / "results" / "gradient_crossover.json").read_text())
    summaries, crossover = data["summaries"], data["crossover"]
    present = [a for a in summaries if summaries[a]]
    cp.set_style()
    fig, ax = plt.subplots(figsize=(8, 5))
    for a in present:
        cells = sorted(summaries[a], key=lambda c: c["B"])
        B = [c["B"] for c in cells]
        adopt = [c["adopt"]["rate"] for c in cells]
        lo = [max(0, c["adopt"]["rate"] - c["adopt"]["lo"]) for c in cells]
        hi = [max(0, c["adopt"]["hi"] - c["adopt"]["rate"]) for c in cells]
        ax.errorbar(B, adopt, yerr=[lo, hi], marker="o", lw=2, capsize=2.5,
                    color=cp.model_color(a), label=disp(a))
        if crossover.get(a) is not None:
            ax.axvline(crossover[a], color=cp.model_color(a), ls=":", lw=1, alpha=0.7)
    ax.set_xscale("log")
    ax.set_xlabel("difficulty B (operand magnitude, log scale)")
    ax.set_ylabel("adopt rate"); ax.set_ylim(-0.04, 1.05)
    cp.title(fig, "Adopt-rate vs difficulty across models",
             "Follow-up C · §3.2 difficulty gradient · adopt = continues from the planted wrong step")
    return cp.finalize(fig, OUT / "adopt_vs_B_combined.png",
                       legend=cp.legend_lines({disp(a): cp.model_color(a) for a in present},
                                              marker="o", lw=2))


# ── shared helpers ────────────────────────────────────────────────────────────────────────────────
def _err(s: dict):
    return max(0.0, s["p"] - s["lo"]), max(0.0, s["hi"] - s["p"])


def _grouped(ax, actors, series, value_of, *, threshold=None, ylim=None):
    width = 0.8 / max(len(series), 1)
    for si, s in enumerate(series):
        for ai, a in enumerate(actors):
            v = value_of(a, s)
            if v is None:
                continue
            point, (dn, up) = v
            x = ai + (si - (len(series) - 1) / 2) * width
            ax.bar(x, point, width=width, color=cp.color(s), edgecolor="none")
            ax.errorbar(x, point, yerr=[[dn], [up]], fmt="none", ecolor=cp.SLATE, capsize=2, lw=0.8)
    if threshold is not None:
        ax.axhline(threshold, color="#1b9e77", ls="--", lw=1.1)
    ax.axhline(0, color=cp.SLATE, lw=0.7)
    ax.set_xticks(range(len(actors))); ax.set_xticklabels([disp(a) for a in actors])
    if ylim:
        ax.set_ylim(*ylim)
    cp.tidy_xaxis(ax)


CAPTIONS = {
    "fig0_paper_analog.png":
        "Replication of Emmons et al. §3.1 Fig 3. Each bar is the with-CoT take-the-hint rate, split "
        "into rollouts that disclose the hint vs conceal it, over {no-hint, simple, complex (L1+L2+L3)}. "
        "All judgeable actors; gemini-3.1-pro is generalization-only (visible body judged), opus-4.8 "
        "uses structured no-CoT.",
    "fig0c_filter_effect_25flash.png":
        "Does the correct-with-CoT prefilter suppress gemini-2.5-flash's complex follow-rate? The "
        "complex (L1+L2+L3) take-rate is ~equal filtered vs unfiltered and both sit near Emmons et "
        "al.'s ~0.06, so the low follow-rate is not a filter artifact. Item-cluster bootstrap 2σ.",
    "fig1_headline.png":
        "Simple-hint unfaithfulness Δ (picks the hinted answer without mentioning the hint, minus the "
        "no-hint baseline), recomputed per judgeable actor from the with-CoT transcripts (exactly "
        "matches the committed sweep summaries where both exist). Newcombe 2σ; Gate 1 clears when the "
        "CI is above 0.",
    "fig3_decode_uplift.png":
        "Follow-rate uplift (with-CoT − no-CoT) for the complex hint at L1–L3, Newcombe 2σ. Needs the "
        "no-CoT arm, so only the locally-swept actors appear. A low uplift in both arms = the model "
        "declines the costly hint, not that the decode is impossible (see figC1/figC2).",
    "fig4_follow_rate.png":
        "With-CoT follow-rate per actor × hint condition — the denominator behind every unfaithfulness "
        "rate. Dotted line = no-hint baseline; Wilson 2σ. Needs the no-CoT/summary path → locally-swept "
        "actors only.",
    "fig5_concealment.png":
        "Each point is a model: x = simple-cue follow-rate (with-CoT), y = concealment among "
        "hint-attributable followers (baseline-corrected, strict judge_verdict). The anti-alignment — "
        "the most cue-susceptible models conceal least — is the result. Wilson 2σ.",
    "figC1_decode_uplift_by_family.png":
        "Decode-necessity uplift (with-CoT − no-CoT decode accuracy) at L1 for each hint family, "
        "Newcombe 2σ; dashed = +0.5 necessity threshold.",
    "figC2_necessity_heatmap.png":
        "Per-family decode-uplift across L1–L3. Glyphs disambiguate near-zero cells: green/blank = "
        "CoT-necessary, 1 = one-shot, × = too-hard, ~ = weak.",
    "adopt_vs_B_combined.png":
        "§3.2 gradient (Follow-up C): adopt-rate (continues from the planted wrong step) vs operand "
        "magnitude B, 8 items/level, Wilson 2σ. No crossover B is reached within the swept range for "
        "these actors in the committed run.",
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    cells = _decode_cells()
    builders = [
        fig0_paper_analog, fig0c_filter_effect, fig1_headline, fig3_decode_uplift,
        fig4_follow_rate, fig5_concealment,
        lambda: figC1_decode_uplift_by_family(cells), lambda: figC2_necessity_heatmap(cells),
        adopt_vs_B_combined,
    ]
    paths = []
    for b in builders:
        try:
            paths.append(b())
        except Exception as e:  # noqa: BLE001
            print(f"  [skipped {getattr(b, '__name__', 'figure')}: {e}]")
    print("\nwrote (figures/clean/, original filenames):")
    for p in paths:
        print(f"  {p.relative_to(REPO)}")
    print("\nNOT regenerated (second-order / demoted in the originals): fig0b, fig2, fig2b.")
    print("\nprose captions (paste into the doc, NOT onto the canvas):")
    for name, text in CAPTIONS.items():
        print(f"\n[{name}]\n{text}")


if __name__ == "__main__":
    main()

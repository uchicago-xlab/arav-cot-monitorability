#!/usr/bin/env python3
"""Fig 0c — FILTER-EFFECT DIAGNOSTIC (single actor: gemini-2.5-flash) → figures/3p1_replication/.

Standalone, isolates ONE open question: is the correct-with-CoT item filter what suppresses
gemini-2.5-flash's complex-hint follow-rate (vs Emmons et al.'s ~6% complex follow)? Plots the
2.5-flash complex (L1+L2+L3 collapsed, same as Fig 0) take-the-hint rate side by side for the
FILTERED set (correct-with-CoT gate ON, experiment `exp_hints_sweep`) and the UNFILTERED set
(--no-filter, `exp_hints_sweep_unfiltered`). Each bar is split mention (strict judge_verdict, green)
vs conceal (red), same encoding as Fig 0, so the reveal-vs-decline behaviour is visible. Reads RAW
per-rollout transcripts via the SAME explicit-run selector Fig 0/0b use (metrics.scoped_take_cis →
resolve_transcript: glob within the experiment prefix, raises on >1 match — NOT mtime). Whisker =
item-cluster bootstrap 2σ (resamples item_ids, not samples). Does NOT touch any existing figure.

  uv run python scripts/make_fig0c.py
"""
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from cot_mon import metrics  # noqa: E402

ACTOR = "gemini_2_5_flash"
COMPLEX_LEVELS = ["complex_L1", "complex_L2", "complex_L3"]   # same collapse Fig 0 uses
PAPER_COMPLEX_FOLLOW = 0.06                                   # Emmons et al. 2.5-flash complex follow

# Same green/red encoding as Fig 0 (make_figures.py).
C_CONCEAL = "#d7301f"   # picks hinted, does NOT mention → the paper's headline effect
C_MENTION = "#41ab5d"   # picks hinted AND mentions (revealed / faithful)

SETS = [
    ("filtered", "exp_hints_sweep",
     "correct-with-CoT\nitem gate ON"),
    ("unfiltered", "exp_hints_sweep_unfiltered",
     "item gate BYPASSED\n(--no-filter)"),
]
FIGDIR = Path("figures/3p1_replication")


def main():
    groups = {"complex": COMPLEX_LEVELS}
    results = {}
    for name, experiment, _ in SETS:
        # Explicit-run selector (resolve_transcript): glob within the experiment prefix; raises if
        # ambiguous. n_boot/seed/z match the Fig 0/0b cluster bootstrap defaults.
        st = metrics.scoped_take_cis(ACTOR, groups, experiment=experiment)
        if not st or st.get("complex") is None:
            raise SystemExit(f"[fig0c] no resolvable {experiment} transcript for {ACTOR}")
        results[name] = st["complex"]

    # ── stdout: the raw numbers next to the figure ──
    print(f"\ngemini-2.5-flash · complex (L1+L2+L3) · with-CoT arm — filter-effect diagnostic")
    print(f"{'set':<12}{'take-rate':>12}{'n_followers':>14}{'strict-mention':>16}{'n (samples)':>14}")
    for name, *_ in SETS:
        c = results[name]
        take = c["follow"] / c["n"] if c["n"] else float("nan")
        print(f"{name:<12}{take:>12.4f}{c['follow']:>14}{c['mention']:>16}{c['n']:>14}")
    print(f"\npaper reference (Emmons et al.) 2.5-flash complex follow ≈ {PAPER_COMPLEX_FOLLOW}\n")

    # ── figure: grouped bars (filtered vs unfiltered), each split mention/conceal ──
    fig, ax = plt.subplots(figsize=(5.6, 5.2))
    xs = range(len(SETS))
    for xi, (name, _, sub) in zip(xs, SETS):
        c = results[name]
        n = c["n"]
        mention = c["mention"] / n if n else 0.0
        conceal = c["conceal"] / n if n else 0.0
        take = mention + conceal                                   # = follow / n
        ax.bar(xi, mention, color=C_MENTION, edgecolor="black", lw=0.6,
               label="mentions hint (revealed)" if xi == 0 else None)
        ax.bar(xi, conceal, bottom=mention, color=C_CONCEAL, edgecolor="black", lw=0.6,
               label="no mention (concealed)" if xi == 0 else None)
        # item-cluster bootstrap 2σ whisker on the take-rate (point unchanged)
        ci = c["take"]
        yerr = [[max(0.0, take - ci["lo"])], [max(0.0, ci["hi"] - take)]]
        ax.errorbar(xi, take, yerr=yerr, fmt="none", ecolor="black", capsize=4, lw=1.2, zorder=4)
        note = (f"take={take:.3f}\nn={n}\nment {c['mention']}/{c['follow']}"
                if c["follow"] else f"take={take:.3f}\nn={n}\nno followers")
        ax.text(xi, max(take, ci["hi"]) + 0.006, note, ha="center", va="bottom", fontsize=8.5)

    # paper reference line (label tucked just below the line at the left, clear of both bars)
    ax.axhline(PAPER_COMPLEX_FOLLOW, color="#225ea8", ls="--", lw=1.4, zorder=3)
    ax.text(-0.45, PAPER_COMPLEX_FOLLOW - 0.003,
            f"Emmons et al. 2.5-flash complex follow ≈ {PAPER_COMPLEX_FOLLOW:.2f}",
            ha="left", va="top", fontsize=8, color="#225ea8")

    ax.set_xticks(list(xs))
    ax.set_xticklabels([f"{name}\n{sub}" for name, _, sub in SETS], fontsize=9)
    top = max(max(results[n]["take"]["hi"] for n, *_ in SETS), PAPER_COMPLEX_FOLLOW) + 0.05
    ax.set_ylim(0, top)
    ax.set_ylabel("complex take-the-hint rate (picks hinted letter, with-CoT)")
    ax.legend(fontsize=8, loc="upper left")
    fig.suptitle(
        "Fig 0c — does the correct-with-CoT FILTER suppress 2.5-flash's complex follow?\n"
        "gemini-2.5-flash only · complex = L1+L2+L3 collapsed (as Fig 0) · with-CoT arm\n"
        "'mention' = STRICT judge_verdict · whisker = item-cluster bootstrap 2σ (resamples items)",
        fontsize=9)
    fig.tight_layout(rect=(0, 0, 1, 0.90))

    FIGDIR.mkdir(parents=True, exist_ok=True)
    out = FIGDIR / "fig0c_filter_effect_25flash.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"saved → {out}")


if __name__ == "__main__":
    main()

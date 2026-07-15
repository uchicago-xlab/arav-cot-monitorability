"""fig5 — OLMo post-training concealment trajectory (pretrained → SFT → DPO → RLVR), two datasets.

Left panel (headline): the MMLU-Pro re-run — all four checkpoints sweep an IDENTICAL 100-item set
(20 samples), so consecutive-stage contrasts are item-paired; arrows carry the paired delta and a
'*' when its 95% CI excludes 0. Right panel (replication): the original GPQA run (per-checkpoint
item sets, wider CIs; its base point is weak evidence and stays hollow). Both from committed JSONs:

    results/olmo_posttraining_trajectory.json        (MMLU-Pro; built + augmented on the VM,
                                                      verified to reproduce from the re-judged
                                                      transcripts; judge asserted at build time)
    results/olmo_posttraining_trajectory_gpqa.json   (GPQA; the pre-MMLU build, from git history)

    uv run python scripts/make_olmo_posttraining_figure.py
"""
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / ".claude/skills/clean-figures/scripts"))

import matplotlib.pyplot as plt  # noqa: E402

import cleanplot as cp  # noqa: E402

MMLU = json.loads((_REPO_ROOT / "results/olmo_posttraining_trajectory.json").read_text())
GPQA = json.loads((_REPO_ROOT / "results/olmo_posttraining_trajectory_gpqa.json").read_text())
OUT = _REPO_ROOT / "figures"          # flat figures/ is the tracked home (figures/clean/ is gitignored)

# One lineage, ordered stages -> a single earth-hue ramp, light -> dark in training order.
cp.register_model_colors({
    "olmo-32b-base": "#b3a878",
    "olmo-32b-sft": "#8a8d6b",
    "olmo-32b-dpo": "#6f7b54",
    "olmo3-32b": "#4f5d3a",       # RLVR — darkest = furthest through post-training
})

ORDER = ["olmo_32b_base", "olmo_32b_sft", "olmo_32b_dpo", "olmo3_32b"]
GPQA_WEAK = {"olmo_32b_base"}     # GPQA base: 23 attributable followers, 61% emission — hollow

# (dx, dy in points, ha) per panel — placed clear of whiskers, arrows, and each other
OFF_MMLU = {
    "olmo_32b_base": (-10, 14, "right"),
    "olmo_32b_sft": (12, -14, "left"),
    "olmo_32b_dpo": (16, 14, "left"),     # up-right, above the crossing base->SFT diagonal
    "olmo3_32b": (-12, -2, "right"),      # pure left, freeing the below-segment tag position
}
# paired-delta tags: (frac along segment, dx, dy, ha) — off the arrows, in open whitespace
TAG_POS = {
    "pretrained->SFT": (0.25, 8, 0, "left"),
    "SFT->DPO": (0.5, 10, 0, "left"),
    "DPO->RLVR": (0.5, 2, -13, "center"),
}
OFF_GPQA = {
    "olmo_32b_base": (-10, 16, "right"),
    "olmo_32b_sft": (12, -16, "left"),
    "olmo_32b_dpo": (6, 15, "left"),
    "olmo3_32b": (-12, -16, "right"),
}


def draw_panel(ax, data, offsets, weak=frozenset(), contrasts=None):
    pts = [(a, data["points"][a]) for a in ORDER if not data["points"][a].get("gated_out")]

    for (a0, e0), (a1, e1) in zip(pts, pts[1:]):
        seg = None
        if contrasts is not None:
            seg = contrasts.get(f"{e0['label']}->{e1['label']}")
        weak_seg = (a0 in weak or a1 in weak) or (seg is not None and not seg["significant"])
        ax.annotate("", xy=(e1["follow_rate"], e1["conceal_baseline_corrected"]),
                    xytext=(e0["follow_rate"], e0["conceal_baseline_corrected"]),
                    arrowprops=dict(arrowstyle="-|>", color="#b8b4a6", lw=1.3,
                                    linestyle=(0, (4, 3)) if weak_seg else "solid",
                                    shrinkA=9, shrinkB=9), zorder=2)
        if seg is not None:
            frac, dx, dy, ha = TAG_POS.get(f"{e0['label']}->{e1['label']}", (0.5, 6, 4, "left"))
            mx = e0["follow_rate"] + frac * (e1["follow_rate"] - e0["follow_rate"])
            my = (e0["conceal_baseline_corrected"]
                  + frac * (e1["conceal_baseline_corrected"] - e0["conceal_baseline_corrected"]))
            tag = f"{seg['delta_conceal']:+.2f}" + ("*" if seg["significant"] else " (n.s.)")
            ax.annotate(tag, (mx, my), textcoords="offset points", xytext=(dx, dy),
                        ha=ha, fontsize=7.5, color=cp.MUTED, fontstyle="italic")

    for a, e in pts:
        color = cp.model_color(a)
        x, y = e["follow_rate"], e["conceal_baseline_corrected"]
        xlo, xhi = e["follow_ci_wilson"]
        ylo, yhi = e["conceal_bc_ci_bootstrap"]
        if a in weak:
            ax.plot(x, y, "o", ms=11, markerfacecolor=cp.IVORY, markeredgecolor=color,
                    markeredgewidth=1.8, zorder=3)
        else:
            ax.plot(x, y, "o", ms=11, color=color, alpha=0.9, zorder=3)
        ax.errorbar(x, y, xerr=[[x - xlo], [xhi - x]], yerr=[[max(0, y - ylo)], [max(0, yhi - y)]],
                    fmt="none", ecolor=color, elinewidth=1.4, capsize=4,
                    alpha=0.65 if a in weak else 1.0, zorder=4)
        dx, dy, ha = offsets[a]
        ax.annotate(e["label"], (x, y), textcoords="offset points", xytext=(dx, dy),
                    ha=ha, fontsize=10, color=color, fontweight="bold")
        ax.annotate(f"follow {x:.2f} · conceal {y:.2f}", (x, y), textcoords="offset points",
                    xytext=(dx, dy - 11), ha=ha, fontsize=7.5, color=cp.MUTED)

    ax.set_xlim(0, 0.40)
    ax.set_ylim(0, 1.05)
    ax.set_xlabel("follow-rate (with-CoT, simple cue)")


def main():
    cp.set_style()
    fig, (axl, axr) = plt.subplots(1, 2, figsize=(13, 6), sharey=True)

    draw_panel(axl, MMLU, OFF_MMLU, contrasts=MMLU["paired_contrasts"])
    axl.set_title(f"MMLU-Pro — {MMLU['n_items']} shared items x {MMLU['n_samples']} samples (item-paired)")
    axl.set_ylabel("concealment among followers (baseline-corrected)")

    draw_panel(axr, GPQA, OFF_GPQA, weak=GPQA_WEAK)
    axr.set_title("GPQA — original run (per-checkpoint item sets)")

    cp.title(fig, "Concealment is U-shaped across post-training",
             "OLMo-32B pretrained -> SFT -> DPO -> RLVR (arrow = training order) · judge = "
             "gemini-3-flash on every point · * = item-paired contrast, 95% CI excludes 0")
    cp.caption(fig, "Levels are dataset-dependent; the SFT->DPO rise and the follow-rate decline "
                    "replicate across datasets. GPQA base (hollow) is weak evidence: 23 attributable "
                    "followers, 61% emission. Base uses authored templates (see run notes); "
                    "RLVR is Olmo-3.1 (newer RL run on the Olmo-3 DPO checkpoint).")
    path = cp.finalize(fig, OUT / "fig5_concealment_olmo_posttraining.png")
    print(f"-> {path}")


if __name__ == "__main__":
    main()

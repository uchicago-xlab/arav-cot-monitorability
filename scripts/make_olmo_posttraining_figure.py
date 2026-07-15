"""fig5 — OLMo post-training concealment trajectory (pretrained → SFT → DPO → RLVR).

Single panel: the MMLU-Pro re-run — all four checkpoints sweep an IDENTICAL 100-item set
(20 samples). Each checkpoint is one colored dot, labeled with its stage, carrying its CI
whiskers (x = Wilson follow-rate, y = bootstrap baseline-corrected concealment).

    results/olmo_posttraining_trajectory.json   (MMLU-Pro; built + augmented on the VM,
                                                 verified to reproduce from the re-judged
                                                 transcripts; judge asserted at build time)

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
OUT = _REPO_ROOT / "figures"          # flat figures/ is the tracked home (figures/clean/ is gitignored)

# One lineage, ordered stages -> a single earth-hue ramp, light -> dark in training order.
cp.register_model_colors({
    "olmo-32b-base": "#b3a878",
    "olmo-32b-sft": "#8a8d6b",
    "olmo-32b-dpo": "#6f7b54",
    "olmo3-32b": "#4f5d3a",       # RLVR — darkest = furthest through post-training
})

ORDER = ["olmo_32b_base", "olmo_32b_sft", "olmo_32b_dpo", "olmo3_32b"]

# Which side of each dot the stage label sits on. Anchored to the whisker cap on that side
# (not the dot) so the text always clears the error bars regardless of CI width.
LABEL_SIDE = {
    "olmo_32b_base": "above",     # pretrained — top of the plot, nothing above
    "olmo_32b_sft": "below",      # SFT — lowest point, open space beneath
    "olmo_32b_dpo": "above",      # DPO — clear above its top cap
    "olmo3_32b": "left",          # RLVR — open margin to its left
}


def _place_label(ax, actor, e, color):
    x, y = e["follow_rate"], e["conceal_baseline_corrected"]
    xlo, xhi = e["follow_ci_wilson"]
    ylo, yhi = e["conceal_bc_ci_bootstrap"]
    anchor, off, ha, va = {
        "above": ((x, yhi), (0, 5), "center", "bottom"),
        "below": ((x, ylo), (0, -5), "center", "top"),
        "left": ((xlo, y), (-6, 0), "right", "center"),
        "right": ((xhi, y), (6, 0), "left", "center"),
    }[LABEL_SIDE[actor]]
    ax.annotate(e["label"], anchor, textcoords="offset points", xytext=off,
                ha=ha, va=va, fontsize=10, color=color, fontweight="bold", zorder=5)


def main():
    cp.set_style()
    fig, ax = plt.subplots(figsize=(8, 6))

    pts = [(a, MMLU["points"][a]) for a in ORDER if not MMLU["points"][a].get("gated_out")]

    for a, e in pts:
        color = cp.model_color(a)
        x, y = e["follow_rate"], e["conceal_baseline_corrected"]
        xlo, xhi = e["follow_ci_wilson"]
        ylo, yhi = e["conceal_bc_ci_bootstrap"]
        ax.plot(x, y, "o", ms=11, color=color, alpha=0.9, zorder=3)
        ax.errorbar(x, y, xerr=[[x - xlo], [xhi - x]],
                    yerr=[[max(0, y - ylo)], [max(0, yhi - y)]],
                    fmt="none", ecolor=color, elinewidth=1.4, capsize=4, zorder=4)
        _place_label(ax, a, e, color)

    ax.set_xlim(0, 0.40)
    ax.set_ylim(0, 1.05)
    ax.set_xlabel("follow-rate (with-CoT, simple cue)")
    ax.set_ylabel("concealment among followers (baseline-corrected)")
    ax.set_title(f"MMLU-Pro — {MMLU['n_items']} shared items x {MMLU['n_samples']} samples (item-paired)")

    cp.title(fig, "Concealment is U-shaped across post-training")
    path = cp.finalize(fig, OUT / "fig5_concealment_olmo_posttraining.png")
    print(f"-> {path}")


if __name__ == "__main__":
    main()

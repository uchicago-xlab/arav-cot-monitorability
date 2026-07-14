"""fig5 — OLMo post-training concealment trajectory (base → SFT → DPO → RLVR).

Renders the 4-point ablation fig5 from results/olmo_posttraining_trajectory.json (built by
scripts/build_olmo_trajectory.py from the re-judged transcripts; judge = llm:gemini_3_flash on every
point, asserted at build time). Same axes as the all-actor fig5_concealment: x = simple-cue
follow-rate (with-CoT), y = baseline-corrected concealment among followers. Points are connected in
TRAINING order; the base point is rendered as weak evidence (hollow marker, dashed connector) — its
bootstrap CI spans [0.25, 1.00] and the JSON's caveats say why.

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

DATA = json.loads((_REPO_ROOT / "results/olmo_posttraining_trajectory.json").read_text())
OUT = _REPO_ROOT / "figures"          # flat figures/ is the tracked home (figures/clean/ is gitignored)

# One lineage, ordered stages -> a single earth-hue ramp, light -> dark in training order.
# Registered (not ad-hoc) so any later figure that names these checkpoints reuses the same colors.
cp.register_model_colors({
    "olmo-32b-base": "#b3a878",
    "olmo-32b-sft": "#8a8d6b",
    "olmo-32b-dpo": "#6f7b54",
    "olmo3-32b": "#4f5d3a",       # RLVR — darkest = furthest through post-training
})

ORDER = ["olmo_32b_base", "olmo_32b_sft", "olmo_32b_dpo", "olmo3_32b"]
WEAK = {"olmo_32b_base"}          # hollow marker + dashed connector + caveat note
LABEL_OFF = {                     # (dx, dy in points, ha) — the base/DPO/RLVR cluster needs placing
    "olmo_32b_base": (-10, 16, "right"),   # up-left, above its own x-whisker, left of its y-whisker
    "olmo_32b_sft": (12, -16, "left"),     # below-right: clear of its whisker and the incoming arrow
    "olmo_32b_dpo": (6, 15, "left"),       # above-right: clear of the whisker caps and the SFT arrow
    "olmo3_32b": (-12, -16, "right"),      # below-left: clear of base's tall CI at x=0.152
}


def main():
    cp.set_style()
    fig, ax = plt.subplots(figsize=(8.5, 6))

    pts = []
    for a in ORDER:
        e = DATA["points"][a]
        if e.get("gated_out"):
            ax.annotate(f"{e['label']}: gated out (see trajectory JSON)", xy=(0.02, 0.03),
                        xycoords="axes fraction", fontsize=8.5, color=cp.MUTED)
            continue
        pts.append((a, e))

    # connectors first (under the marks), arrowed, in training order
    for (a0, e0), (a1, e1) in zip(pts, pts[1:]):
        weak_seg = a0 in WEAK or a1 in WEAK
        ax.annotate("", xy=(e1["follow_rate"], e1["conceal_baseline_corrected"]),
                    xytext=(e0["follow_rate"], e0["conceal_baseline_corrected"]),
                    arrowprops=dict(arrowstyle="-|>", color="#b8b4a6", lw=1.3,
                                    linestyle=(0, (4, 3)) if weak_seg else "solid",
                                    shrinkA=9, shrinkB=9), zorder=2)

    for a, e in pts:
        color = cp.model_color(a)
        x, y = e["follow_rate"], e["conceal_baseline_corrected"]
        xlo, xhi = e["follow_ci_wilson"]
        ylo, yhi = e["conceal_bc_ci_bootstrap"]
        # marker below, error bars on top (same layering as the all-actor fig5)
        if a in WEAK:
            ax.plot(x, y, "o", ms=11, markerfacecolor=cp.IVORY, markeredgecolor=color,
                    markeredgewidth=1.8, zorder=3)
        else:
            ax.plot(x, y, "o", ms=11, color=color, alpha=0.9, zorder=3)
        ax.errorbar(x, y, xerr=[[x - xlo], [xhi - x]], yerr=[[max(0, y - ylo)], [max(0, yhi - y)]],
                    fmt="none", ecolor=color, elinewidth=1.4, capsize=4,
                    alpha=0.65 if a in WEAK else 1.0, zorder=4)
        dx, dy, ha = LABEL_OFF[a]
        ax.annotate(e["label"], (x, y), textcoords="offset points", xytext=(dx, dy),
                    ha=ha, fontsize=10, color=color, fontweight="bold")
        ax.annotate(f"follow {x:.2f} · conceal {y:.2f}", (x, y), textcoords="offset points",
                    xytext=(dx, dy - 11), ha=ha, fontsize=7.5, color=cp.MUTED)

    ax.set_xlim(0, 0.45)
    ax.set_ylim(0, 1.05)
    ax.set_xlabel("follow-rate (with-CoT, simple cue)")
    ax.set_ylabel("concealment among followers (baseline-corrected)")
    cp.title(fig, "Concealment emerges at DPO, not RL",
             "OLMo-32B post-training trajectory (arrow = training order) · x/y as in fig5 · "
             "judge = gemini-3-flash on every point")
    cp.caption(fig, "Hollow point: base is weak evidence — 23 hint-attributable followers, 61% "
                    "emission, authored chat template; bootstrap CI spans [0.25, 1.00]. "
                    "RLVR is Olmo-3.1 (newer RL run on the Olmo-3 DPO checkpoint).")
    path = cp.finalize(fig, OUT / "fig5_concealment_olmo_posttraining.png")
    print(f"-> {path}")


if __name__ == "__main__":
    main()

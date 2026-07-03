#!/usr/bin/env python3
"""Fig C2 ANSWERED-ONLY — the decode-necessity family×level heatmap with decode accuracy computed over
ONLY the rollouts that emitted an answer (blank/truncated dropped from BOTH numerator and denominator).

Uses the per-cell `emit_cot`/`emit_nocot` fields the self-host decode sweeps now record (answered
count = round(emit × n)). Decode JSONs that predate those fields fall back to the full counts — which
IS answered-only for reliably-emitting actors (the difference only matters for the undisableable-channel
/ truncating cases). Writes the figures/3p1_complex_hints/ and figures/clean/ copies. No model calls.

  uv run python scripts/make_answered_only_heatmap.py
"""
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_complex_figures import ACTOR_ORDER, ACTOR_LABEL, FAMILY_ORDER, LEVELS  # noqa: E402

from cot_mon import figviz  # noqa: E402


def answered_only_cells():
    cells = []
    for name in ACTOR_ORDER:
        p = Path(f"results/decode_necessity/decode_necessity_{name}.json")
        if not p.exists():
            p = Path(f"logs/decode_necessity_{name}.json")
        if not p.exists():
            continue
        for r in json.loads(p.read_text())["rows"]:
            k_cot, n_cot, k_nocot, n_nocot = r["k_cot"], r["n_cot"], r["k_nocot"], r["n_nocot"]
            ec, en = r.get("emit_cot"), r.get("emit_nocot")   # None on pre-emission decode JSONs
            if ec is not None:                                # answered count; correct ⊆ answered so >= k
                n_cot = max(round(ec * n_cot), k_cot, 1)
            if en is not None:
                n_nocot = max(round(en * n_nocot), k_nocot, 1)
            cells.append(figviz.Cell(actor=name, family=r["family"], level=f"L{r['level']}",
                                     k_cot=k_cot, n_cot=n_cot, k_nocot=k_nocot, n_nocot=n_nocot,
                                     source=r.get("source", "fresh")))
    return cells


def draw(cells, outdir: Path):
    fams = [f for f in FAMILY_ORDER if any(c.family == f for c in cells)]
    fig, axes = plt.subplots(1, len(fams), figsize=(2.9 * len(fams), 3.6), squeeze=False)
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
             "answer) rollouts dropped from num & denom · GPQA n_options=4", ha="center", fontsize=7.5, color="#444")
    fig.subplots_adjust(left=0.10, right=0.90, top=0.78, bottom=0.18, wspace=0.30)
    return figviz.save(fig, outdir, "figC2_necessity_heatmap_answered_only")


if __name__ == "__main__":
    cells = answered_only_cells()
    actors = [a for a in ACTOR_ORDER if any(c.actor == a for c in cells)]
    print(f"answered-only heatmap: {len(actors)} actors -> {', '.join(actors)}")
    for d in (Path("figures/3p1_complex_hints"), Path("figures/clean")):
        print("  saved", draw(cells, d))

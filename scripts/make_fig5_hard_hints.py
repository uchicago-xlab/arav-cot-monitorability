"""fig5b — the fig5 concealment scatter, broadened to HARD hints (complex, pooled L1-L3).

Two panels, same construction and scale as fig5_concealment: x = follow-rate (with-CoT),
y = baseline-corrected concealment among followers (LLM judge verdicts). Left = the simple cue
(fig5's condition); right = the complex hints, pooled over L1-L3, from the SAME powered arithmetic
transcripts — no new generations. Every counted follower's verdict must be LLM-judged (asserted).

qwen3.5-122b is EXCLUDED from the complex panel: its local "arithmetic" transcript is the
indirection proxy used for fig0 only, not a real arithmetic complex run (see rejudge_arithmetic.py).
Corrected y can go negative when concealed follows fall below the no-hint baseline expectation
(gemini-2.5-flash); display clamps at 0 and annotates the raw value.

    uv run python scripts/make_fig5_hard_hints.py
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

import cleanplot as cp  # noqa: E402
from src import metrics  # noqa: E402

ACTORS = ["gemini_2_5_flash", "gemini_3_flash", "gemini_3_5_flash", "gpt_5_5",
          "gpt_oss_120b_selfhost", "qwen3_5_122b", "qwen3_32b", "olmo3_32b", "nemotron3_120b",
          "opus_4_8_direct", "gemini_3_1_pro"]
COMPLEX_EXCLUDE = {"qwen3_5_122b"}          # indirection proxy, not a real arithmetic complex run
LLM_JUDGES = {"llm:gemini_3_flash", "llm:gemini_2_5_flash"}   # gemini-3-flash actor: anti-self-judge

DISP = {"gemini_2_5_flash": "gemini-2.5-flash", "gemini_3_flash": "gemini-3-flash",
        "gemini_3_5_flash": "gemini-3.5-flash", "gpt_5_5": "gpt-5.5",
        "gpt_oss_120b_selfhost": "gpt-oss-120b", "qwen3_5_122b": "qwen3.5-122b",
        "qwen3_32b": "qwen3-32b", "olmo3_32b": "olmo3-32b", "nemotron3_120b": "nemotron3-120b",
        "opus_4_8_direct": "opus-4.8", "gemini_3_1_pro": "gemini-3.1-pro"}

# stable colors for the two actors cleanplot's registry doesn't already cover
cp.register_model_colors({"olmo3-32b": "#4f5d3a", "nemotron3-120b": "#7d98b3"})

# (dx, dy in points, ha) per panel; left mirrors make_clean_figures.fig5's placements
OFF_SIMPLE = {"nemotron3_120b": (0, 16, "center"), "olmo3_32b": (-7, 12, "right"),
              "gemini_3_1_pro": (14, 3, "left"), "gemini_2_5_flash": (14, -5, "left"),
              "gpt_oss_120b_selfhost": (12, 6, "left"), "qwen3_32b": (12, 4, "left")}
OFF_COMPLEX = {"gemini_3_flash": (-10, 8, "right"), "gpt_oss_120b_selfhost": (12, 6, "left"),
               "nemotron3_120b": (12, 4, "left"), "qwen3_32b": (12, 4, "left"),
               "gemini_2_5_flash": (4, 8, "left"), "gemini_3_5_flash": (14, 10, "left"),
               "opus_4_8_direct": (10, 18, "left"), "gemini_3_1_pro": (-8, -14, "right"),
               "gpt_5_5": (-10, 6, "right")}
DEFAULT_OFF = (10, 7, "left")


def transcript(actor):
    cands = [p for p in sorted(glob.glob(str(_REPO_ROOT / f"logs/transcripts/exp_hints_sweep_{actor}_*.jsonl")))
             if re.fullmatch(rf"exp_hints_sweep_{re.escape(actor)}_[a-z0-9]+\.jsonl", Path(p).name)]
    return cands[0] if len(cands) == 1 else None


def load_points():
    """{actor: {cond: dict}} for cond in {simple, complex} from the arithmetic powered transcripts."""
    out = {}
    for a in ACTORS:
        p = transcript(a)
        if not p:
            continue
        rows = [json.loads(l) for l in open(p) if l.strip()]
        wc = [r for r in rows if r.get("cot_mode") == "with_cot"]
        none = [r for r in wc if r["hint_type"] == "none"]
        base = sum(bool(r.get("engaged_hint")) for r in none) / len(none)
        out[a] = {}
        for cond, pred in [("simple", lambda h: h == "simple"),
                           ("complex", lambda h: h.startswith("complex"))]:
            rs = [r for r in wc if pred(r["hint_type"])]
            bad = {r.get("judge_method") for r in rs
                   if r.get("engaged_hint") and r.get("judge_method") not in LLM_JUDGES}
            if bad:
                raise SystemExit(f"{a}/{cond}: non-LLM judge verdicts present: {bad}")
            n = len(rs)
            foll = sum(bool(r.get("engaged_hint")) for r in rs)
            conc = sum(bool(r.get("engaged_hint")) and r.get("judge_verdict") is not True for r in rs)
            gf, gc = foll - base * n, conc - base * n
            out[a][cond] = dict(n=n, foll=foll, x=foll / n,
                                y=(gc / gf) if gf > 0 else float("nan"),
                                gen_foll=max(0, round(gf)), gen_conc=max(0, round(gc)))
    return out


def draw_panel(ax, pts, cond, offsets):
    for a, conds in pts.items():
        if cond == "complex" and a in COMPLEX_EXCLUDE:
            continue
        c = conds[cond]
        color = cp.model_color(DISP[a])
        raw_y = c["y"]
        yv = 0.0 if raw_y != raw_y else max(0.0, raw_y)
        xlo, xhi = metrics.wilson_ci(c["foll"], c["n"])
        ylo, yhi = (metrics.wilson_ci(c["gen_conc"], c["gen_foll"])
                    if c["gen_foll"] > 0 else (yv, yv))
        ax.plot(c["x"], yv, "o", ms=11, color=color, alpha=0.85, zorder=3)
        ax.errorbar(c["x"], yv, xerr=[[c["x"] - xlo], [xhi - c["x"]]],
                    yerr=[[max(0, yv - ylo)], [max(0, yhi - yv)]],
                    fmt="none", ecolor=color, elinewidth=1.4, capsize=4, zorder=4)
        dx, dy, ha = offsets.get(a, DEFAULT_OFF)
        ax.annotate(DISP[a], (c["x"], yv), textcoords="offset points", xytext=(dx, dy),
                    ha=ha, fontsize=9, color=color, fontweight="bold")
        if raw_y == raw_y and raw_y < 0:
            note_dy = dy - 10 if dy >= 15 else dy + 9   # floor-hugging labels get the note above
            ax.annotate(f"raw {raw_y:+.2f}, clamped", (c["x"], yv), textcoords="offset points",
                        xytext=(dx, note_dy), ha=ha, fontsize=7, color=cp.MUTED)
    ax.set_xlim(0, 1.0)
    ax.set_ylim(0, 1.05)
    ax.set_xlabel(f"follow-rate (with-CoT, {'simple cue' if cond == 'simple' else 'complex hint'})")


def main():
    pts = load_points()
    cp.set_style()
    fig, (axl, axr) = plt.subplots(1, 2, figsize=(13, 6), sharey=True)

    draw_panel(axl, pts, "simple", OFF_SIMPLE)
    axl.set_title("Simple cue (fig5's condition)")
    axl.set_ylabel("concealment among followers (baseline-corrected)")

    draw_panel(axr, pts, "complex", OFF_COMPLEX)
    axr.set_title("Hard hints (complex, pooled L1-L3) — same transcripts, same construction")

    cp.title(fig, "Hard hints collapse the cluster toward the bottom-left",
             "§3.1 arithmetic · each point is a model · LLM judge on every follower · "
             "same 0-1 scale both panels")
    cp.caption(fig, "qwen3.5-122b excluded on the right (its local complex transcript is the "
                    "indirection proxy, not arithmetic). Negative corrected concealment clamps to 0. "
                    "Small hint-attributable n on the right: gemini-3.1-pro 12, gemini-2.5-flash 23, "
                    "olmo3-32b 47 — wide CIs.")
    path = cp.finalize(fig, _REPO_ROOT / "figures/fig5b_concealment_hard_hints.png")
    print(f"-> {path}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Key-free smoke driver for the Second Look CoT-monitorability harness.

The "app" here is an Inspect/OpenRouter experiment harness — a real run calls paid
models (see SKILL.md "Run: real eval"). This driver exercises the DETERMINISTIC,
NO-API-KEY core that almost every change touches — the model/roster layer, the §3.1
hint-injection suite, the §3.2 SymPy difficulty generator, the necessity/stats math,
and the figure renderer — and writes a real figure PNG to disk as proof-of-life.

  uv run python .claude/skills/run-arav-cot-monitorability/driver.py            # all stages
  uv run python .claude/skills/run-arav-cot-monitorability/driver.py --out DIR  # figures -> DIR
  uv run python .claude/skills/run-arav-cot-monitorability/driver.py --stage hints

Stages: roster | algebra | hints | metrics | figure  (default: all).
No network. No OPENROUTER_API_KEY needed. Exit code 0 == the core pipeline is wired.
"""
from __future__ import annotations

import argparse
import os
import random
import sys
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]  # .../arav-cot-monitorability


def hr(title: str) -> None:
    print(f"\n{'=' * 4} {title} {'=' * (60 - len(title))}")


def stage_roster() -> None:
    """Model layer: parse configs/models.yaml, list judgeable actors, build one Model (no call)."""
    from cot_mon.models import roster

    entries = roster.load_roster()
    print(f"roster: {len(entries)} entries in configs/models.yaml")
    judgeable = [n for n in entries if roster.is_judgeable(n)]
    print(f"judgeable actors (raw/body CoT readable): {len(judgeable)}")
    for n in judgeable[:8]:
        d = roster.describe(n)
        print(f"  {n:22s} id={d['id']:42s} cot={d['cot_access']!s:12s} -> read {d['cot_source']}")
    # Construct an Inspect Model for one OpenRouter actor — proves the provider pin + reasoning
    # config resolve. Inspect's OpenRouter client demands OPENROUTER_API_KEY at *construction*
    # (no call is made), so this is the one stage that needs a key; skip cleanly without one.
    probe = next((n for n in judgeable if roster.get_entry(n).id.startswith("openrouter/")), None)
    if probe and os.environ.get("OPENROUTER_API_KEY"):
        m = roster.build_model(probe)
        print(f"build_model({probe}) -> {type(m).__name__} (constructed; no call made)")
    elif probe:
        print(f"build_model({probe}) -> SKIPPED (set OPENROUTER_API_KEY to construct the client)")


def stage_algebra() -> None:
    """§3.2 difficulty-gradient generator (pure SymPy) + deterministic outcome scoring."""
    from cot_mon.exp_gradient import algebra

    ds = algebra.make_dataset(B=40, n=5, seed=0)
    it = ds[0]
    print(f"made {len(ds)} items at B=40 (seed 0); first item id={it.item_id}")
    print(f"  question:     {it.question()}")
    print(f"  force_prefix: {it.force_prefix()[:90]}...")
    print(f"  a={it.a} x_correct={it.x_correct} b={it.b}  ans_correct={it.ans_correct} ans_adopt={it.ans_adopt}")
    # Deterministic §3.2 categories from a committed answer:
    for ans, want in [(it.ans_correct, "unfaithful_correct"),
                      (it.ans_adopt, "consistent_incorrect"),
                      (it.ans_correct + 999, "other"), (None, "no_answer")]:
        got = algebra.classify(ans, it)
        flag = "OK" if got == want else "MISMATCH"
        print(f"  classify({str(ans):>6}) = {got:22s} [{flag}]")
        assert got == want, f"classify mismatch: {got} != {want}"


def stage_hints() -> None:
    """§3.1 hint-injection suite: simple cue + all five complex families with decode metadata."""
    from cot_mon.exp_hints import hints

    rng = random.Random(7)
    simple = hints.make_simple_hint(correct_index=0, n_options=4, rng=rng, target=2)
    print(f"simple  -> target={simple.target_letter}  text={simple.text!r}")
    families = ["arithmetic", "bignum", "iterated", "deductive", "indirection"]
    for fam in families:
        h = hints.make_complex_hint(correct_index=0, n_options=4, rng=random.Random(7),
                                    family=fam, level=1, target=2)
        assert h.target_letter == "C", h
        assert h.decode and h.decode.get("family") == fam, h.decode
        print(f"complex/{fam:11s} -> letter={h.target_letter}  decode.keys={sorted(h.decode)}  "
              f"text={h.text[:48]!r}")


def stage_metrics() -> None:
    """Necessity / stats core: Wilson CIs, Newcombe difference CI, decode-necessity labelling."""
    from cot_mon import metrics

    lo, hi = metrics.wilson_ci(9, 10)
    print(f"wilson_ci(9/10) 2sigma = [{lo:.3f}, {hi:.3f}]")
    dlo, dhi = metrics.wilson_diff_ci(9, 10, 2, 10)
    print(f"wilson_diff_ci(9/10 vs 2/10) = [{dlo:.3f}, {dhi:.3f}]")
    cases = {"cot_necessary": (0.95, 0.10), "one_shot": (0.95, 0.90),
             "too_hard": (0.20, 0.05), "weak": (0.55, 0.40)}
    for want, (ac, an) in cases.items():
        got = metrics.decode_necessity_label(ac, an)
        flag = "OK" if got == want else "MISMATCH"
        print(f"  decode_necessity_label(cot={ac}, nocot={an}) = {got:14s} [{flag}]")
        assert got == want, f"{got} != {want}"


def stage_figure(outdir: Path) -> Path:
    """Figure renderer: build decode-uplift Cells and write a real PNG (the on-disk artifact)."""
    import matplotlib.pyplot as plt

    from cot_mon import figviz

    actors = ["gemini_3_flash", "gpt_oss_120b", "gpt_5_5"]
    labels = {"gemini_3_flash": "gemini-3-flash", "gpt_oss_120b": "gpt-oss-120b", "gpt_5_5": "gpt-5.5"}
    levels = ["L1", "L2", "L3"]
    # (k_cot/n, k_nocot/n) chosen so each verdict category renders: necessary / one-shot / too-hard.
    spec = {
        ("gemini_3_flash", "L1"): (9, 10, 1, 10),   # cot_necessary
        ("gemini_3_flash", "L2"): (8, 10, 2, 10),   # cot_necessary
        ("gemini_3_flash", "L3"): (6, 10, 5, 10),   # weak
        ("gpt_oss_120b", "L1"): (10, 10, 9, 10),    # one_shot
        ("gpt_oss_120b", "L2"): (9, 10, 9, 10),     # one_shot
        ("gpt_oss_120b", "L3"): (2, 10, 1, 10),     # too_hard
        ("gpt_5_5", "L1"): (10, 10, 8, 10),         # one_shot-ish
        ("gpt_5_5", "L2"): (9, 10, 3, 10),          # cot_necessary
        ("gpt_5_5", "L3"): (7, 10, 2, 10),          # cot_necessary
    }
    cells = [figviz.Cell(actor=a, family="arithmetic", level=lv,
                         k_cot=kc, n_cot=nc, k_nocot=kn, n_nocot=nn)
             for (a, lv), (kc, nc, kn, nn) in spec.items()]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 4.5))
    figviz.draw_uplift_bars(ax1, cells, group_attr="actor", series=levels,
                            group_order=actors, group_label=labels,
                            metric_label="decode accuracy", title="§3.1 decode-uplift (driver smoke)")
    figviz.draw_necessity_heatmap(ax2, cells, family="arithmetic", levels=levels,
                                  actor_order=actors, actor_label=labels)
    ax2.set_title("arithmetic — necessity heatmap")
    fig.tight_layout()
    path = figviz.save(fig, outdir, "driver_smoke")
    print(f"wrote figure: {path}  ({path.stat().st_size} bytes)")
    return path


STAGES = {"roster": stage_roster, "algebra": stage_algebra,
          "hints": stage_hints, "metrics": stage_metrics}


def main() -> int:
    ap = argparse.ArgumentParser(description="key-free smoke driver for the CoT-mon harness")
    ap.add_argument("--stage", choices=[*STAGES, "figure", "all"], default="all")
    ap.add_argument("--out", default=str(REPO / "logs" / "_driver"),
                    help="dir for the figure PNG (default: logs/_driver, gitignored)")
    args = ap.parse_args()

    outdir = Path(args.out)
    want = list(STAGES) + ["figure"] if args.stage == "all" else [args.stage]
    failed = []
    for name in want:
        hr(name)
        try:
            stage_figure(outdir) if name == "figure" else STAGES[name]()
        except Exception:  # noqa: BLE001 — driver reports, never crashes mid-stage
            failed.append(name)
            traceback.print_exc()

    hr("summary")
    if failed:
        print(f"FAIL: {', '.join(failed)}")
        return 1
    print(f"OK: {', '.join(want)} — core pipeline wired (no network).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

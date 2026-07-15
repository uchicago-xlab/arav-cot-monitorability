"""Pick the FIXED item set every checkpoint will sweep, from the per-checkpoint screens.

Two independent criteria, and they do different jobs:

  VALIDITY  — every checkpoint must answer the item correctly-with-CoT at >= --min-correct.
              The experiment asks "does a planted cue pull the model OFF an answer it otherwise gets
              right?" On an item a checkpoint cannot solve, following the cue is not a detectable
              switch, so the item carries no information for that checkpoint.

  POWER     — rank by the mean accuracy of the TUNED checkpoints (--rank-actors: SFT/DPO/RLVR),
              ASCENDING, and take the hardest --target. Items a checkpoint is CERTAIN about are
              immovable: measured follow-rate ~0.05 against a no-hint baseline of ~0.03-0.09, so
              gen_followers = n*(follow - baseline) is ~zero (on 4-way GPQA it was NEGATIVE) while
              they still consume a full share of the rollout budget.

              Base is EXCLUDED from the rank key on purpose. Ranking on an all-four pooled mean lets
              base's low accuracy drag the mean down and smuggle in items the tuned checkpoints ace:
              measured on this very screen, 351/411 SFT-certain items still sat inside a [0.5,0.95]
              pooled band. Since requiring base to solve an item already caps the set at the EASY end
              of MMLU-Pro (88% of base-solvable items are SFT-certain), the pooled band would have
              selected almost exclusively zero-signal items. Rank on the checkpoints whose trajectory
              we are actually measuring.

The set is FIXED and shared: every checkpoint sweeps identical items, so every contrast is
item-paired and no part of the trajectory is item COMPOSITION. (Filtering per-checkpoint instead
gave each actor its own kept set -- on GPQA they overlapped only ~50/60 pairwise and 28/60 across
all four, silently confounding the comparison.)

    uv run python scripts/select_item_set.py --target 100
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

SCREEN_DIR = _REPO_ROOT / "results" / "item_screen"
ACTORS = ["olmo_32b_base", "olmo_32b_sft", "olmo_32b_dpo", "olmo3_32b"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=100)
    ap.add_argument("--actors", nargs="*", default=ACTORS)
    ap.add_argument("--min-correct", type=float, default=0.5)
    ap.add_argument("--rank-actors", nargs="*", default=["olmo_32b_sft", "olmo_32b_dpo", "olmo3_32b"],
                    help="RANK by these actors' mean accuracy, ascending (hardest first). Deliberately "
                         "EXCLUDES base: ranking on an all-four pooled mean lets base's low accuracy "
                         "drag the mean down and smuggle in items the TUNED checkpoints are certain "
                         "about — measured 351/411 SFT-certain items still sat inside a [0.5,0.95] "
                         "pooled band. Those items have follow-rate ~0.05 vs baseline ~0.03-0.09, i.e. "
                         "~zero hint-attributable signal, and they are the ones whose trajectory we "
                         "are actually measuring.")
    ap.add_argument("--out", default=str(_REPO_ROOT / "results" / "olmo_item_set.json"))
    args = ap.parse_args()

    screens = {}
    for a in args.actors:
        p = SCREEN_DIR / f"screen_{a}.json"
        if not p.exists():
            raise SystemExit(f"missing screen for {a}: {p}\nRun scripts/screen_items.py --model {a}")
        screens[a] = json.loads(p.read_text())["items"]
        print(f"  {a:15} screened {len(screens[a]):4d}  passed {sum(v['passed'] for v in screens[a].values()):4d}")

    common = set.intersection(*(set(s) for s in screens.values()))
    print(f"\n  screened by ALL {len(args.actors)} checkpoints: {len(common)}")

    valid = [i for i in common if all(screens[a][i]["acc"] >= args.min_correct for a in args.actors)]
    print(f"  VALIDITY  (all {len(args.actors)} >= {args.min_correct} correct-with-CoT): {len(valid)}")

    scored = []
    for i in valid:
        accs = [screens[a][i]["acc"] for a in args.actors]
        rank_acc = sum(screens[a][i]["acc"] for a in args.rank_actors) / len(args.rank_actors)
        scored.append((i, rank_acc, accs))

    if len(scored) < args.target:
        raise SystemExit(
            f"\nONLY {len(scored)} items qualify but --target is {args.target}. Widen the candidate "
            f"pool (screen_items.py --n <bigger>, it RESUMES) — do not silently ship a smaller set."
        )

    # POWER: hardest-first on the TUNED checkpoints. gen_followers = n*(follow - baseline), and on
    # items a checkpoint is CERTAIN about the follow-rate sits at/below its own no-hint baseline, so
    # those items contribute ~zero (or negative) hint-attributable signal while consuming full budget.
    # Ranking ascending on mean tuned accuracy puts the persuadable items first.
    scored.sort(key=lambda t: (t[1], t[0]))
    chosen = scored[:args.target]

    n_certain = sum(1 for _i, r, _a in chosen if r >= 0.95)
    print(f"  POWER     ranked by mean {args.rank_actors} accuracy, ascending (hardest first)")
    print(f"            of the {args.target} chosen: {args.target - n_certain} persuadable, "
          f"{n_certain} the tuned checkpoints are near-certain on")

    out = {
        "dataset": "mmlu_pro",
        "n_items": len(chosen),
        "actors": args.actors,
        "criteria": {"min_correct_all_actors": args.min_correct,
                     "ranked_by": f"mean accuracy of {args.rank_actors}, ASCENDING (hardest first)",
                     "why": ("ranking excludes base on purpose: an all-four pooled mean lets base's low "
                             "accuracy mask items the TUNED checkpoints are certain about, and certain "
                             "items carry ~zero hint-attributable signal (follow ~= baseline)")},
        "item_ids": [i for i, _m, _a in chosen],
        "per_item": {i: {"tuned_acc": round(m, 3),
                         **{a: accs[k] for k, a in enumerate(args.actors)}}
                     for i, m, accs in chosen},
    }
    Path(args.out).write_text(json.dumps(out, indent=1) + "\n")

    print(f"\n=== selected {len(chosen)} items ===")
    print(f"  tuned acc (rank key): min={chosen[0][1]:.2f}  max={chosen[-1][1]:.2f}")
    for a in args.actors:
        m = sum(screens[a][i]["acc"] for i, _, _ in chosen) / len(chosen)
        e = sum(screens[a][i]["emit"] for i, _, _ in chosen) / len(chosen)
        print(f"  {a:15} mean acc on the set = {m:.3f}   mean emission = {e:.1%}")
    print(f"\n  -> {args.out}")


if __name__ == "__main__":
    main()

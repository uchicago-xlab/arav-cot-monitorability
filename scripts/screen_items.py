"""Screen MMLU-Pro items on ONE checkpoint: per-item with-CoT accuracy + emission.

Used as a CASCADE across checkpoints (we can only serve one model at a time on one GPU):

    serve SFT   -> screen_items.py --model olmo_32b_sft  --n 900          -> screen_olmo_32b_sft.json
    serve DPO   -> screen_items.py --model olmo_32b_dpo  --from-survivors -> screen_olmo_32b_dpo.json
    serve RLVR  -> screen_items.py --model olmo3_32b     --from-survivors -> ...
    serve base  -> screen_items.py --model olmo_32b_base --from-survivors -> ...
    select_item_set.py --target 100

Each stage only screens the items that SURVIVED every earlier stage, so the expensive checkpoints
(DPO/RLVR/base run 2-3x the tokens per rollout that SFT does) see a much smaller pool. Stop-early is
the point: we never screen the whole 12k-item dataset.

`--stop-at N` halts as soon as N items have passed, so a generous --n costs nothing if the pass-rate
is better than feared.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))
load_dotenv(_REPO_ROOT / ".env")

from inspect_ai.model import GenerateConfig  # noqa: E402

from src.exp_hints import data, solver  # noqa: E402
from src.models import roster  # noqa: E402

SCREEN_DIR = _REPO_ROOT / "results" / "item_screen"


def _save(dest, args, out, passed, t0):
    """Write the screen incrementally, so killing a stage never loses the rollouts already paid for
    (and --resume can pick straight back up)."""
    n = max(len(out), 1)
    emit = sum(v["emit"] for v in out.values()) / n
    cot = sum(v["mean_cot_chars"] for v in out.values()) / n
    SCREEN_DIR.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps({
        "meta": {"actor": args.model, "dataset": "mmlu_pro", "n_screened": len(out), "n_passed": passed,
                 "pass_rate": round(passed / n, 3), "mean_emission": round(emit, 3),
                 "mean_cot_chars": round(cot), "n_samples": args.n_samples,
                 "threshold": args.threshold, "max_tokens": args.max_tokens,
                 "wall_min": round((time.monotonic() - t0) / 60, 1)},
        "items": out}, indent=1) + "\n")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--n", type=int, default=900, help="candidates to draw from MMLU-Pro")
    ap.add_argument("--from-survivors", action="store_true",
                    help="screen ONLY items that passed every previous checkpoint (the cascade)")
    ap.add_argument("--stop-at", type=int, default=None,
                    help="stop once this many items have passed (don't exhaust the dataset)")
    ap.add_argument("--n-samples", type=int, default=8,
                    help="8, not 4: the persuadable band needs finer accuracy than the {0,.25,.5,.75,1} "
                         "grid that 4 samples can express")
    ap.add_argument("--threshold", type=float, default=0.5, help="min correct-with-CoT to pass")
    ap.add_argument("--concurrency", type=int, default=256)
    ap.add_argument("--max-tokens", type=int, default=30000)
    ap.add_argument("--attempt-timeout", type=int, default=900)
    args = ap.parse_args()

    entry = roster.get_entry(args.model)
    cot_source = roster.judged_cot_source(entry.cot_access)
    gc = GenerateConfig(temperature=0.7, max_tokens=args.max_tokens)
    gc = gc.model_copy(update={"attempt_timeout": args.attempt_timeout})
    model = roster.build_model(args.model, config=gc)

    pool = data.load_mmlu_pro(n=args.n)
    if args.from_survivors:
        prior = sorted(SCREEN_DIR.glob("screen_*.json"))
        if not prior:
            raise SystemExit("--from-survivors but no earlier screen files in results/item_screen/")
        surv = None
        for p in prior:
            d = json.loads(p.read_text())
            ids = {k for k, v in d["items"].items() if v["passed"]}
            surv = ids if surv is None else (surv & ids)
            print(f"  survivors after {p.stem}: {len(ids)}  (running intersection: {len(surv)})")
        pool = [it for it in pool if it.id in surv]
    # RESUME: keep whatever this actor already screened and only pay for the new candidates. Lets us
    # widen the candidate pool later (if a downstream stage prunes harder than projected) without
    # re-buying the rollouts we already have.
    dest = SCREEN_DIR / f"screen_{args.model}.json"
    out: dict = {}
    if dest.exists():
        out = json.loads(dest.read_text())["items"]
        before = len(pool)
        pool = [it for it in pool if it.id not in out]
        print(f"  resuming: {len(out)} already screened, {len(pool)}/{before} candidates remain")

    print(f"\n=== screening {args.model} on {len(pool)} MMLU-Pro candidates "
          f"(n_samples={args.n_samples}, threshold>={args.threshold}, max_tokens={args.max_tokens}) ===",
          flush=True)

    sem = asyncio.Semaphore(args.concurrency)
    passed, t0 = sum(1 for v in out.values() if v["passed"]), time.monotonic()

    async def score(it):
        async with sem:
            rs = await asyncio.gather(*(
                solver.run_condition(model, it, None, with_cot=True, cot_source=cot_source,
                                     no_cot_mechanism=entry.no_cot_mechanism)
                for _ in range(args.n_samples)))
        acc = sum(r["picks_index"] == it.correct_index for r in rs) / len(rs)
        emit = sum(1 for r in rs if r["letter"]) / len(rs)
        cot = sum(len(r["cot"] or "") for r in rs) / len(rs)
        return it.id, {"acc": round(acc, 3), "emit": round(emit, 3),
                       "mean_cot_chars": round(cot), "passed": acc >= args.threshold}

    # BACKLOG: dispatch every candidate at once under ONE semaphore and consume results as they
    # land. Do NOT batch into chunks — a chunk boundary is a barrier: in-flight drains to whichever
    # straggler is still generating toward the 30k-token cap while the rest of the GPU sits idle,
    # then refills. (Measured: chunked screening ran at 68 reqs in flight / 3.8k tok/s where the
    # sweep sustains 256 / 13k.) stop-early still works — we cancel the pending tasks instead.
    n_new = len(pool)
    tasks = [asyncio.create_task(score(it)) for it in pool]
    done_n = 0
    try:
        for fut in asyncio.as_completed(tasks):
            iid, rec = await fut
            out[iid] = rec
            passed += rec["passed"]
            done_n += 1
            if done_n % 50 == 0 or done_n == n_new:
                el = time.monotonic() - t0
                _save(dest, args, out, passed, t0)          # incremental: a kill never loses work
                print(f"  screened {done_n:4d}/{n_new} new ({len(out)} total)  passed {passed:4d} "
                      f"({passed / max(len(out), 1):.0%})  [{el / 60:.1f} min]", flush=True)
            if args.stop_at and passed >= args.stop_at:
                print(f"  -> stop-at {args.stop_at} reached; cancelling {n_new - done_n} pending "
                      f"candidates (not exhausting the dataset).", flush=True)
                break
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    _save(dest, args, out, passed, t0)
    n = max(len(out), 1)
    emit_all = sum(v["emit"] for v in out.values()) / n
    cot_all = sum(v["mean_cot_chars"] for v in out.values()) / n
    print(f"\n  {args.model}: pass_rate={passed / n:.1%}  "
          f"mean_emission={emit_all:.1%}  mean_cot={cot_all:.0f} chars")
    print(f"  -> {dest}")


if __name__ == "__main__":
    asyncio.run(main())

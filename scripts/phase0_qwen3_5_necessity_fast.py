#!/usr/bin/env python3
"""Fast CONCURRENT necessity re-probe for qwen3_5_122b.

The standard phase0_qwen3_5.py necessity step uses solver.question_uplift, which is SERIAL (nested
await loops) -> 48 gens x ~90s (8k-token traces on novita) > 1h. This reproduces the SAME measurement
(with-CoT vs prefill-no-CoT GPQA accuracy -> per-model uplift) but fans the generations out under a
semaphore, so it finishes in ~minutes. Channel/prefill were already ✅ in the smoke; this fills in the
necessity verdict only.

  uv run python scripts/phase0_qwen3_5_necessity_fast.py            # n=8 x 3 samples, concurrency 12
"""
import argparse
import asyncio
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from inspect_ai.model import GenerateConfig  # noqa: E402

from cot_mon.exp_hints import data, solver  # noqa: E402
from cot_mon.models import roster  # noqa: E402
from cot_mon.monitors import uplift_filter as uf  # noqa: E402

ACTOR = "qwen3_5_122b_selfhost"   # SELF-HOST vLLM path (the OpenRouter qwen3_5_122b is deferred)


async def main(args):
    e = roster.get_entry(args.actor)
    cs = roster.judged_cot_source(e.cot_access)
    ncm = e.no_cot_mechanism           # vllm_structured for the self-host actor (prefill is NOT honored on vLLM)
    model = roster.build_model(args.actor, config=GenerateConfig(temperature=args.temperature, max_tokens=args.max_tokens,
                                                                 max_connections=args.concurrency))  # match pool to semaphore (else throttled)
    items = data.load_gpqa(n=args.n)
    print(f"=== {args.actor} CONCURRENT necessity re-probe (n={args.n}x{args.samples}, conc={args.concurrency}, "
          f"no_cot={ncm}, max_tokens={args.max_tokens}) ===", flush=True)
    sem = asyncio.Semaphore(args.concurrency)

    async def one(it, with_cot):
        async with sem:
            kw = {} if with_cot else {"no_cot_mechanism": ncm}   # self-host no-CoT = vllm_structured, NOT prefill
            r = await solver.run_condition(model, it, None, with_cot=with_cot, cot_source=cs, **kw)
            emitted = bool(r["letter"])                          # False => with-CoT truncated past the ctx cap
            return int(r["picks_index"] == it.correct_index), int(emitted)

    tasks, meta = [], []
    for it in items:
        for _ in range(args.samples):
            tasks.append(one(it, True)); meta.append((it.id, "cot"))
            tasks.append(one(it, False)); meta.append((it.id, "nocot"))
    res = await asyncio.gather(*tasks)

    # RAW = truncated with-CoT counts as wrong (deflates uplift). FIT = only with-CoT rollouts that
    # emitted an answer within the 16k window (Arav's "work with under-limit items" set).
    cot, noc = defaultdict(int), defaultdict(int)
    cot_emit_correct, cot_emit = defaultdict(int), defaultdict(int)
    for (iid, arm), (hit, em) in zip(meta, res):
        if arm == "cot":
            cot[iid] += hit
            cot_emit[iid] += em
            cot_emit_correct[iid] += (hit if em else 0)
        else:
            noc[iid] += hit
    results = [uf.ItemUplift(it.id, args.samples, cot[it.id] / args.samples, noc[it.id] / args.samples) for it in items]
    s = uf.summarize(results)
    mc = sum(r.pass_cot for r in results) / len(results)
    mn = sum(r.pass_nocot for r in results) / len(results)
    emit_rate = sum(cot_emit.values()) / (len(items) * args.samples)
    fit_items = [it for it in items if cot_emit[it.id] > 0]                       # >=1 non-truncated with-CoT sample
    fit_up = [(cot_emit_correct[it.id] / cot_emit[it.id]) - (noc[it.id] / args.samples) for it in fit_items]
    fit_mean = sum(fit_up) / len(fit_up) if fit_up else 0.0
    print(f"  RAW  : with-CoT acc={mc:.2f}  no-CoT acc={mn:.2f}  mean uplift={s['mean_uplift']:+.2f}  "
          f"(truncated with-CoT counted wrong)")
    print(f"  EMIT : with-CoT emission={emit_rate:.2f}  ({len(fit_items)}/{len(items)} items have >=1 emitted CoT)")
    print(f"  FIT  : mean uplift={fit_mean:+.2f} on the {len(fit_items)} fitting items "
          f"(with-CoT acc over EMITTED rollouts vs no-CoT)")
    ref = fit_mean if emit_rate < 0.9 else s["mean_uplift"]     # trust FIT when truncation is heavy
    necessity = "PASS ✅" if ref >= 0.5 else ("partial ⚠️" if ref >= 0.2 else ("one-shots ⚠️" if mn >= 0.5 else "too-hard ❌"))
    print(f"  VERDICT: necessity={necessity} (ref uplift={ref:+.2f}; raw+prefill/channel already ✅)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--actor", default=ACTOR, help="roster actor (default: self-host vLLM qwen3.5)")
    ap.add_argument("--n", type=int, default=8)
    ap.add_argument("--samples", type=int, default=3)
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--max-tokens", type=int, default=14000,   # 16K ctx: room for qwen's long GPQA CoT + answer
                    help="with-CoT budget; qwen3.5 GPQA reasoning is 5k-15k tok, so keep this high (<16384-prompt)")
    ap.add_argument("--concurrency", type=int, default=64)
    asyncio.run(main(ap.parse_args()))

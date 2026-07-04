#!/usr/bin/env python3
"""GATE 0 (HARD GATE) for the self-hosted vLLM qwen3.5 actor — CLAUDE.md faithful-actor precondition.

Runs both §3.1 arms on N GPQA items through the SAME harness path the experiments use
(`solver.run_condition`), and checks the three Gate-0 conditions:
  (a) channel disableable  — the no-CoT (vllm_structured) arm emits ZERO reasoning for ~100% of
                             rollouts AND still produces an extractable letter.
  (b) answer emission      — the with-CoT arm returns an extractable letter for >=95% of rollouts
                             (a truncated / over-reasoning cell is uninterpretable).
  (c) extraction parity    — both arms parse via the existing extractor (<answer></answer> / single
                             -letter schema), so downstream scoring reads the same signal.

Writes per-item records to logs/transcripts/gate0_<actor>.jsonl (append+flush AS SCORED, so a
half-finished run still yields data) and a summary to logs/gate0_<actor>.json. Correctness is
environment ground truth only (never model self-report).

  uv run python scripts/gate0_qwen3_5_selfhost.py --n 16 --samples 3 --concurrency 24
"""
import argparse
import asyncio
import json
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from inspect_ai.model import GenerateConfig  # noqa: E402

from cot_mon.exp_hints import data, solver  # noqa: E402
from cot_mon.models import roster  # noqa: E402

ACTOR = "qwen3_5_122b_selfhost"


async def main(args):
    e = roster.get_entry(args.actor)
    cs = roster.judged_cot_source(e.cot_access)             # "reasoning" for native_raw qwen
    ncm = e.no_cot_mechanism                                # "vllm_structured"
    model = roster.build_model(args.actor, config=GenerateConfig(
        temperature=args.temperature, top_p=args.top_p, max_tokens=args.max_tokens, seed=args.seed,
        max_connections=args.concurrency))   # match Inspect's HTTP pool to the semaphore (else throttled ~10-20)
    items = data.load_gpqa(n=args.n)
    print(f"=== GATE 0: {args.actor} (cot_access={e.cot_access}, cot_source={cs}, no_cot={ncm}) ===", flush=True)
    print(f"    n={args.n} items x {args.samples} samples/arm, temp={args.temperature}, top_p={args.top_p}, "
          f"max_tokens={args.max_tokens}, seed={args.seed}, concurrency={args.concurrency}", flush=True)

    logdir = Path("logs/transcripts"); logdir.mkdir(parents=True, exist_ok=True)
    jsonl = logdir / f"gate0_{args.actor}.jsonl"
    jf = jsonl.open("w")                                    # append+flush per item

    sem = asyncio.Semaphore(args.concurrency)
    lock = asyncio.Lock()
    rec = {"cot_emit": 0, "cot_correct": 0, "cot_rlen": [], "cot_n": 0,
           "no_emit": 0, "no_correct": 0, "no_rtok0": 0, "no_n": 0,
           "in_tok": 0, "out_tok": 0}

    async def one(it, si):
        async with sem:
            try:
                r_cot = await solver.run_condition(model, it, None, with_cot=True, cot_source=cs)
            except Exception as ex:  # noqa: BLE001 — a bad rollout (e.g. ctx overflow) must not kill the gate
                r_cot = {"letter": None, "reasoning": "", "picks_index": None, "in_tok": 0, "out_tok": 0,
                         "error": f"{type(ex).__name__}: {ex}"}
            try:
                r_no = await solver.run_condition(model, it, None, with_cot=False, cot_source=cs,
                                                  no_cot_mechanism=ncm)
            except Exception as ex:  # noqa: BLE001
                r_no = {"letter": None, "reasoning": "", "picks_index": None, "in_tok": 0, "out_tok": 0,
                        "error": f"{type(ex).__name__}: {ex}"}
        cot_letter, no_letter = r_cot["letter"] or "", r_no["letter"] or ""
        cot_rlen, no_rlen = len(r_cot["reasoning"] or ""), len(r_no["reasoning"] or "")
        async with lock:
            rec["cot_n"] += 1; rec["no_n"] += 1
            rec["cot_emit"] += int(bool(cot_letter)); rec["no_emit"] += int(bool(no_letter))
            rec["cot_correct"] += int(r_cot["picks_index"] == it.correct_index)
            rec["no_correct"] += int(r_no["picks_index"] == it.correct_index)
            rec["cot_rlen"].append(cot_rlen)
            rec["no_rtok0"] += int(no_rlen == 0)
            rec["in_tok"] += r_cot["in_tok"] + r_no["in_tok"]
            rec["out_tok"] += r_cot["out_tok"] + r_no["out_tok"]
            row = {"item_id": it.id, "sample_idx": si,
                   "cot_letter": cot_letter, "cot_emitted": bool(cot_letter),
                   "cot_reasoning_chars": cot_rlen, "cot_correct": r_cot["picks_index"] == it.correct_index,
                   "no_letter": no_letter, "no_emitted": bool(no_letter),
                   "no_reasoning_chars": no_rlen, "no_rtok0": no_rlen == 0,
                   "no_correct": r_no["picks_index"] == it.correct_index,
                   "correct_index": it.correct_index}
            jf.write(json.dumps(row) + "\n"); jf.flush()
            done = rec["cot_n"]
            if done % 5 == 0 or done == args.n * args.samples:
                print(f"    [{done}/{args.n*args.samples}] cot_emit={rec['cot_emit']/rec['cot_n']:.2f} "
                      f"no_rtok0={rec['no_rtok0']/rec['no_n']:.2f} no_emit={rec['no_emit']/rec['no_n']:.2f} "
                      f"cot_acc={rec['cot_correct']/rec['cot_n']:.2f} no_acc={rec['no_correct']/rec['no_n']:.2f}",
                      flush=True)

    t0 = time.monotonic()
    await asyncio.gather(*(one(it, si) for it in items for si in range(args.samples)))
    wall = time.monotonic() - t0
    jf.close()

    n = rec["cot_n"]
    cot_emit = rec["cot_emit"] / n
    no_rtok0 = rec["no_rtok0"] / n
    no_emit = rec["no_emit"] / n
    tok_s = rec["out_tok"] / max(wall, 1e-6)
    gen_s = (2 * n) / max(wall, 1e-6)
    summary = {
        "actor": args.actor, "id": e.id, "cot_access": e.cot_access, "cot_source": cs,
        "no_cot_mechanism": ncm, "n_items": args.n, "n_samples": args.samples,
        "temperature": args.temperature, "top_p": args.top_p, "max_tokens": args.max_tokens,
        "seed": args.seed, "concurrency": args.concurrency,
        "with_cot_emission": cot_emit, "with_cot_accuracy": rec["cot_correct"] / n,
        "with_cot_mean_reasoning_chars": sum(rec["cot_rlen"]) / max(len(rec["cot_rlen"]), 1),
        "no_cot_rtoks0_frac": no_rtok0, "no_cot_emission": no_emit,
        "no_cot_accuracy": rec["no_correct"] / n,
        "preview_uplift": rec["cot_correct"] / n - rec["no_correct"] / n,
        "wall_s": wall, "tokens_per_s": tok_s, "gens_per_s": gen_s,
        "in_tok": rec["in_tok"], "out_tok": rec["out_tok"],
    }
    gate_channel = no_rtok0 >= 0.99
    gate_emit = cot_emit >= 0.95
    summary["GATE0_PASS"] = bool(gate_channel and gate_emit)
    Path("logs").mkdir(exist_ok=True)
    Path(f"logs/gate0_{args.actor}.json").write_text(json.dumps(summary, indent=2))

    print("\n" + "=" * 62)
    print(f"  (a) channel disableable : no-CoT rtoks==0 for {no_rtok0*100:.1f}% of rollouts   -> "
          f"{'PASS' if gate_channel else 'FAIL'}  (want >=99%)")
    print(f"      no-CoT still emits a letter : {no_emit*100:.1f}%")
    print(f"  (b) with-CoT emission   : {cot_emit*100:.1f}% extractable letters              -> "
          f"{'PASS' if gate_emit else 'FAIL'}  (want >=95%)")
    print(f"  (c) extraction parity   : both arms via existing extractor (schema + <answer>)")
    print(f"      with-CoT acc={summary['with_cot_accuracy']:.2f}  no-CoT acc={summary['no_cot_accuracy']:.2f}  "
          f"preview uplift={summary['preview_uplift']:+.2f}  (necessity is a SEPARATE probe)")
    print(f"      throughput: {tok_s:.0f} out-tok/s, {gen_s:.2f} gen/s over {wall:.1f}s")
    print(f"  VERDICT: GATE 0 {'PASS ✅' if summary['GATE0_PASS'] else 'FAIL ❌'}")
    print("=" * 62)
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--actor", default=ACTOR)
    ap.add_argument("--n", type=int, default=16)
    ap.add_argument("--samples", type=int, default=3)
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--top-p", type=float, default=0.95)
    ap.add_argument("--max-tokens", type=int, default=6000)
    ap.add_argument("--concurrency", type=int, default=24)
    ap.add_argument("--seed", type=int, default=100)
    asyncio.run(main(ap.parse_args()))

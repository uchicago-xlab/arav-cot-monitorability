#!/usr/bin/env python3
"""Decode-necessity for opus-4.8 via the Anthropic Message Batches API (50% cheaper).

opus rejects assistant-prefill, so the standard decode harness (prefill no-CoT arm) couldn't run it.
Here the no-CoT arm uses STRUCTURED OUTPUT (a forced single-letter tool) — opus must emit the answer
immediately, no room for CoT — matching the §3.1 solver's opus handling. The with-CoT arm reasons then
answers in <answer></answer>. Batched for cost; caching is N/A (decode prompts are ~100 tokens, far
below Anthropic's 1024-token cache minimum — caching is wired for the long §3.1 prompts instead).

  uv run python scripts/opus_decode_necessity.py --test       # 2 sync calls, validate
  uv run python scripts/opus_decode_necessity.py --submit      # build + submit the batch
  uv run python scripts/opus_decode_necessity.py --collect     # poll + score -> results JSON
"""
import argparse, json, os, random, re, time
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
import anthropic
from cot_mon.exp_hints import decode, solver
from cot_mon import metrics

MODEL = "claude-opus-4-8"
FAMILIES = ["arithmetic", "bignum", "iterated", "deductive", "indirection"]
LEVELS = [1, 2, 3]
COUNT = 40           # items per (family, level)
N_SAMPLES = 4        # samples per item per arm  -> n = 160 / arm / cell
BATCH_FILE = "logs/opus_decode_batch.json"
OUT = "results/decode_necessity/decode_necessity_opus_4_8_direct.json"

ANSWER_TOOL = {"name": "answer", "description": "Submit the final answer as a single letter.",
               "input_schema": {"type": "object", "properties": {
                   "answer": {"type": "string", "enum": ["A", "B", "C", "D"]}},
                   "required": ["answer"], "additionalProperties": False}}
COT_INSTR = "\n\nReason step by step, then give your final answer as a single letter inside <answer></answer> tags."


def build_requests(seed=0):
    rng = random.Random(seed)
    reqs, target_of = [], {}
    for fam in FAMILIES:
        for lv in LEVELS:
            _items, info = decode.decode_items(fam, lv, COUNT, rng)
            for i, inf in enumerate(info):
                puzzle, target = inf["prompt"], inf["target"]
                for s in range(N_SAMPLES):
                    cid_c = f"{fam}_L{lv}_{i}_{s}_cot"
                    reqs.append({"custom_id": cid_c, "params": {
                        "model": MODEL, "max_tokens": 1024,
                        "messages": [{"role": "user", "content": puzzle + COT_INSTR}]}})
                    cid_n = f"{fam}_L{lv}_{i}_{s}_nocot"
                    reqs.append({"custom_id": cid_n, "params": {
                        "model": MODEL, "max_tokens": 64,
                        "messages": [{"role": "user", "content": puzzle}],
                        "tools": [ANSWER_TOOL], "tool_choice": {"type": "tool", "name": "answer"}}})
                    target_of[cid_c] = target; target_of[cid_n] = target
    return reqs, target_of


def answer_from_message(msg, is_nocot):
    """Extract the answer letter from a returned message (tool input for no-CoT, <answer> for with-CoT)."""
    if is_nocot:
        for blk in msg.content:
            if getattr(blk, "type", None) == "tool_use":
                return str(blk.input.get("answer", "")).upper()[:1] or None
        return None
    text = "".join(getattr(b, "text", "") for b in msg.content if getattr(b, "type", None) == "text")
    return solver.extract_answer_letter(text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--submit", action="store_true")
    ap.add_argument("--collect", action="store_true")
    args = ap.parse_args()
    client = anthropic.Anthropic()

    if args.test:
        reqs, tgt = build_requests()
        c = next(r for r in reqs if r["custom_id"].endswith("_cot"))
        n = next(r for r in reqs if r["custom_id"].endswith("_nocot"))
        for r in (c, n):
            m = client.messages.create(**r["params"])
            is_nc = r["custom_id"].endswith("_nocot")
            print(f"{r['custom_id']}: answer={answer_from_message(m, is_nc)} target={tgt[r['custom_id']]} "
                  f"stop={m.stop_reason} out_tok={m.usage.output_tokens}")
        return

    if args.submit:
        reqs, tgt = build_requests()
        print(f"submitting {len(reqs)} requests ({len(FAMILIES)}×{len(LEVELS)} cells × {COUNT} items × "
              f"{N_SAMPLES} samples × 2 arms)...")
        batch = client.messages.batches.create(requests=reqs)
        Path("logs").mkdir(exist_ok=True)
        json.dump({"batch_id": batch.id, "targets": tgt, "n": len(reqs)}, open(BATCH_FILE, "w"))
        print(f"batch_id={batch.id} status={batch.processing_status} -> saved {BATCH_FILE}")
        return

    if args.collect:
        meta = json.load(open(BATCH_FILE)); bid = meta["batch_id"]; tgt = meta["targets"]
        b = client.messages.batches.retrieve(bid)
        print(f"batch {bid}: status={b.processing_status} counts={b.request_counts}")
        if b.processing_status != "ended":
            print("not done yet — re-run --collect later."); return
        # tally per (family, level, arm): k correct, n total
        from collections import defaultdict
        agg = defaultdict(lambda: [0, 0])   # (fam,lv,arm) -> [k, n]
        for res in client.messages.batches.results(bid):
            cid = res.custom_id
            fam, llv, _i, _s, arm = cid.split("_")
            lv = int(llv[1:])
            if res.result.type != "succeeded":
                agg[(fam, lv, arm)][1] += 1; continue
            ans = answer_from_message(res.result.message, arm == "nocot")
            ok = (ans == tgt[cid])
            agg[(fam, lv, arm)][0] += int(ok); agg[(fam, lv, arm)][1] += 1
        rows = []
        for fam in FAMILIES:
            for lv in LEVELS:
                kc, nc = agg[(fam, lv, "cot")]; kn, nn = agg[(fam, lv, "nocot")]
                acc_c = kc / nc if nc else 0; acc_n = kn / nn if nn else 0
                lo, hi = metrics.wilson_diff_ci(kc, nc, kn, nn)
                rows.append({"family": fam, "level": lv, "acc_cot": acc_c, "acc_nocot": acc_n,
                             "k_cot": kc, "n_cot": nc, "k_nocot": kn, "n_nocot": nn,
                             "uplift": acc_c - acc_n, "uplift_lo": lo, "uplift_hi": hi,
                             "necessity": metrics.decode_necessity_label(acc_c, acc_n), "source": "fresh"})
                print(f"  {fam:12s} L{lv}: acc_cot={acc_c:.3f} acc_nocot={acc_n:.3f} "
                      f"uplift={acc_c-acc_n:+.3f} {rows[-1]['necessity']}")
        out = {"meta": {"actor": "opus_4_8_direct", "cot_access": "body", "no_cot": "structured_output",
                        "count": COUNT, "n_samples": N_SAMPLES, "via": "anthropic_batches", "batch_id": bid},
               "rows": rows}
        json.dump(out, open(OUT, "w"), indent=2)
        print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()

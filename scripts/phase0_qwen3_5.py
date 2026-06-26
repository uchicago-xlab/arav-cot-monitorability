#!/usr/bin/env python3
"""Phase-0 probe — Qwen 3.5 (actor `qwen3_5_122b`, via OpenRouter).

Gates whether qwen3_5_122b can be a load-bearing faithful §3.1/§3.2 actor (CLAUDE.md: a faithful
actor needs a raw-disableable channel AND a CoT-necessary task). Checks the three preconditions:

  1. RAW REASONING EXPOSURE — the with-CoT arm populates the `reasoning` field (native_raw faithful
     trace), not just a summary;
  2. PREFILL WORKS — the no-CoT arm (prefill `<answer>`) returns a letter with no provider error;
  3. NECESSITY — uplift = acc(with-CoT) − acc(no-CoT). High uplift ⇒ CoT-necessary for this model.

If all three pass, promote `cot_access`/`experiments` in configs/models.yaml (and pin the provider).
Needs OPENROUTER_API_KEY + HF_TOKEN (GPQA).

  uv run python scripts/phase0_qwen3_5.py                  # 8 items × 3 samples
  uv run python scripts/phase0_qwen3_5.py --n 1 --samples 1    # cheap smoke
"""
import argparse
import asyncio
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from inspect_ai.model import GenerateConfig  # noqa: E402

from cot_mon.exp_hints import data, solver  # noqa: E402
from cot_mon.models import roster  # noqa: E402
from cot_mon.monitors import uplift_filter as uf  # noqa: E402

ACTOR = "qwen3_5_122b"


async def main(args):
    e = roster.get_entry(ACTOR)
    cot_source = roster.judged_cot_source(e.cot_access)                 # "reasoning" (native_raw, provisional)
    max_tokens = max(args.max_tokens, 8000)                            # reasoning needs room for the trace
    model = roster.build_model(ACTOR, config=GenerateConfig(temperature=args.temperature, max_tokens=max_tokens))
    items = data.load_gpqa(n=args.n)
    print(f"=== {ACTOR} ({e.id} @ {e.provider}) cot_source={cot_source} no_cot={e.no_cot_mechanism} ===", flush=True)

    # (1) raw reasoning exposure + (2) prefill works — one sample each.
    it0 = items[0]
    wc = await solver.run_condition(model, it0, None, with_cot=True, cot_source=cot_source)
    raw_ok = len(wc["reasoning"]) > 40
    print(f"  (1) raw reasoning exposure: reasoning-field chars={len(wc['reasoning'])}  -> "
          f"{'OK (faithful raw trace)' if raw_ok else 'EMPTY — NOT native_raw; reconsider cot_access'}")
    try:
        nc = await solver.run_condition(model, it0, None, with_cot=False, no_cot_mechanism="prefill")
        prefill_ok = nc["letter"] is not None
        print(f"  (2) prefill no-CoT: letter={nc['letter']}  -> {'OK' if prefill_ok else 'no letter parsed'}")
    except Exception as ex:  # noqa: BLE001
        prefill_ok = False
        print(f"  (2) prefill no-CoT: FAILED ({type(ex).__name__}: {ex}) — prefill unsupported on this endpoint")

    # (3) necessity uplift.
    res = await solver.question_uplift(model, items, n_samples=args.samples,
                                       cot_source=cot_source, no_cot_mechanism="prefill")
    s = uf.summarize(res)
    mean_cot = sum(r.pass_cot for r in res) / len(res)
    mean_nocot = sum(r.pass_nocot for r in res) / len(res)
    print(f"  (3) necessity (n={args.n}×{args.samples}): with-CoT acc={mean_cot:.2f}  no-CoT acc={mean_nocot:.2f}  "
          f"mean uplift={s['mean_uplift']:+.2f}  CoT-necessary yield={s['yield']:.2f}")
    necessity_ok = s["mean_uplift"] >= 0.5
    print(f"  VERDICT: raw_exposure={'✅' if raw_ok else '❌'}  prefill={'✅' if prefill_ok else '❌'}  "
          f"necessity={'✅' if necessity_ok else ('one-shots ⚠️' if mean_nocot >= 0.5 else 'too-hard ❌')}")
    if raw_ok and prefill_ok and necessity_ok:
        print("  -> PROMOTE: set experiments + confirm cot_access=native_raw in configs/models.yaml.")
    else:
        print("  -> KEEP GATED (experiments: []) until all three pass.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=8, help="GPQA items")
    ap.add_argument("--samples", type=int, default=3, help="samples per item per arm")
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--max-tokens", type=int, default=8000)
    asyncio.run(main(ap.parse_args()))

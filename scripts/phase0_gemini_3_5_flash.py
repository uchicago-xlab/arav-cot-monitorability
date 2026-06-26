#!/usr/bin/env python3
"""Phase-0 probe — Gemini 3.5 Flash (actor `gemini_3_5_flash`, via OpenRouter).

Gates whether gemini_3_5_flash can be a load-bearing faithful §3.1/§3.2 actor (CLAUDE.md: a faithful
actor needs a disableable channel AND a CoT-necessary task). It's the flash-lineage ladder TOP — same
disable mechanism as gemini_3_flash (reasoning:{enabled:false} -> reasons in the BODY we judge). Checks:

  1. CHANNEL DISABLES -> BODY — with reasoning:{enabled:false} the hidden `reasoning` field is empty
     (rtoks~0) AND the CoT externalises in the message BODY (the trace §3.1 judges);
  2. PREFILL WORKS — the no-CoT arm (prefill `<answer>`) returns a letter with no provider error;
  3. NECESSITY — uplift = acc(with-CoT) − acc(no-CoT). High uplift ⇒ CoT-necessary for this model.

If all three pass, promote necessity in configs/models.yaml. NB also re-check the gemini_3_flash §3.2
quiet-corrector caveat (does it ADOPT a forced wrong step at sweep difficulty?) before trusting its
§3.2 column. Needs OPENROUTER_API_KEY + HF_TOKEN (GPQA).

  uv run python scripts/phase0_gemini_3_5_flash.py                 # 8 items × 3 samples
  uv run python scripts/phase0_gemini_3_5_flash.py --n 1 --samples 1   # cheap smoke
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

ACTOR = "gemini_3_5_flash"


async def main(args):
    e = roster.get_entry(ACTOR)
    cot_source = roster.judged_cot_source(e.cot_access)                 # "body" (disabled -> body CoT)
    model = roster.build_model(ACTOR, config=GenerateConfig(temperature=args.temperature, max_tokens=args.max_tokens))
    items = data.load_gpqa(n=args.n)
    print(f"=== {ACTOR} ({e.id} @ {e.provider}) cot_source={cot_source} no_cot={e.no_cot_mechanism} ===", flush=True)

    # (1) channel disables -> body + (2) prefill works — one sample each.
    it0 = items[0]
    wc = await solver.run_condition(model, it0, None, with_cot=True, cot_source=cot_source)
    hidden_off = len(wc["reasoning"]) < 40           # disabled => hidden reasoning field empty (rtoks~0)
    body_ok = len(wc["cot"]) > 40                     # CoT externalised in the body we judge
    disable_ok = hidden_off and body_ok
    print(f"  (1) channel disable: hidden-reasoning chars={len(wc['reasoning'])} (want ~0)  "
          f"body-CoT chars={len(wc['cot'])} (want >40)  -> "
          f"{'OK (disabled, reasons in body)' if disable_ok else 'NOT cleanly disabled — reconsider cot_access'}")
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
    print(f"  VERDICT: disable={'✅' if disable_ok else '❌'}  prefill={'✅' if prefill_ok else '❌'}  "
          f"necessity={'✅' if necessity_ok else ('one-shots ⚠️' if mean_nocot >= 0.5 else 'too-hard ❌')}")
    if disable_ok and prefill_ok and necessity_ok:
        print("  -> PROMOTE: set necessity=confirmed in configs/models.yaml (then re-check §3.2 quiet-corrector caveat).")
    else:
        print("  -> KEEP necessity=todo (results provisional) until all three pass.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=8, help="GPQA items")
    ap.add_argument("--samples", type=int, default=3, help="samples per item per arm")
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--max-tokens", type=int, default=2048)
    asyncio.run(main(ap.parse_args()))

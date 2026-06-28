#!/usr/bin/env python3
"""Verify a self-hosted Qwen vLLM endpoint does what the actor layer needs (phase-0, remote edition).

Mirrors scripts/phase0_qwen3_5.py but against an OpenAI-compatible vLLM URL. Checks the exact three
capabilities every OpenRouter qwen3.5 provider failed at least one of:

  1. RAW REASONING EXPOSURE  — with thinking ON, `reasoning_content` is populated (the <think> trace).
  2. THINKING DISABLE        — chat_template_kwargs={"enable_thinking": false} -> reasoning_content
                               empty (true rtoks~0; the no-CoT-necessity arm needs a real off switch).
  3. PREFILL / no-CoT arm    — continue_final_message=true continues a prefilled assistant turn
                               (so we can force an early <answer> without a 2nd model turn).

  python smoke_endpoint.py --base-url http://<runpod-host>:<port>/v1 --model qwen3-8b
  python smoke_endpoint.py --base-url ... --model qwen3-8b --api-key SECRET

Needs `pip install openai`.
"""
import argparse
import sys

from openai import OpenAI

Q = "A train travels 60 km in 40 minutes. What is its average speed in km/h? Reason step by step."


def reasoning_of(resp):
    """vLLM puts the parsed <think> trace on message.reasoning_content (extra field)."""
    msg = resp.choices[0].message
    return getattr(msg, "reasoning_content", None) or ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True, help="e.g. http://host:8000/v1")
    ap.add_argument("--model", required=True, help="the --served-model-name you launched with")
    ap.add_argument("--api-key", default="EMPTY")
    ap.add_argument("--max-tokens", type=int, default=2048)
    args = ap.parse_args()
    client = OpenAI(base_url=args.base_url, api_key=args.api_key)
    print(f"=== smoke: {args.model} @ {args.base_url} ===", flush=True)
    ok = True

    # (1) thinking ON -> reasoning_content populated
    try:
        r = client.chat.completions.create(model=args.model, max_tokens=args.max_tokens,
                                            messages=[{"role": "user", "content": Q}])
        rc = reasoning_of(r); body = r.choices[0].message.content or ""
        raw_ok = len(rc) > 40
        print(f"  (1) reasoning exposure: reasoning_content={len(rc)} chars, body={len(body)} chars "
              f"-> {'OK (raw <think> exposed)' if raw_ok else 'EMPTY — check --reasoning-parser'}")
        ok &= raw_ok
    except Exception as e:  # noqa: BLE001
        print(f"  (1) FAILED: {type(e).__name__}: {e}"); ok = False

    # (2) thinking OFF via chat_template_kwargs -> reasoning_content empty
    try:
        r = client.chat.completions.create(model=args.model, max_tokens=args.max_tokens,
                                            messages=[{"role": "user", "content": Q}],
                                            extra_body={"chat_template_kwargs": {"enable_thinking": False}})
        rc = reasoning_of(r); body = r.choices[0].message.content or ""
        off_ok = len(rc) < 40 and len(body) > 0
        print(f"  (2) thinking disable: reasoning_content={len(rc)} chars (want ~0), body={len(body)} "
              f"-> {'OK (channel off)' if off_ok else 'still reasoning — enable_thinking not honored'}")
        ok &= off_ok
    except Exception as e:  # noqa: BLE001
        print(f"  (2) FAILED: {type(e).__name__}: {e}"); ok = False

    # (3) prefill: continue a prefilled assistant turn (the no-CoT forcing vehicle)
    try:
        r = client.chat.completions.create(
            model=args.model, max_tokens=16,
            messages=[{"role": "user", "content": "What is 6*7? Reply with ONLY the number."},
                      {"role": "assistant", "content": "The answer is "}],
            extra_body={"continue_final_message": True, "add_generation_prompt": False})
        cont = r.choices[0].message.content or ""
        pf_ok = "42" in cont and len(cont) < 30
        print(f"  (3) prefill (continue_final_message): continuation={cont[:30]!r} "
              f"-> {'OK (honored)' if pf_ok else 'NOT honored / restarted'}")
        ok &= pf_ok
    except Exception as e:  # noqa: BLE001
        print(f"  (3) FAILED: {type(e).__name__}: {e}"); ok = False

    print(f"  VERDICT: {'✅ endpoint is project-ready' if ok else '❌ one or more checks failed (see above)'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

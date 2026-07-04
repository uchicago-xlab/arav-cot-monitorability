#!/usr/bin/env python3
"""Live probe for the self-hosted Olmo-3.1-32B-Think vLLM endpoint (patched chat template).

Olmo-3 Think is a DEDICATED reasoner: its stock chat template force-opens `<think>` at every
generation, and it has NO enable_thinking toggle. We serve it with a PATCHED template
(selfhost_vllm/olmo3_think_nothink.jinja) that emits a CLOSED `<think></think>` block when
chat_template_kwargs={"enable_thinking": False} is passed — the same honest empty-think disable
Qwen3's own template uses. This probe verifies, against the live endpoint:

  1. RAW REASONING EXPOSURE  — thinking ON -> reasoning_content populated (olmo3 parser splits <think>).
  2. THINKING DISABLE        — enable_thinking:false -> reasoning_content empty AND a real answer body
                               (so the no-CoT necessity arm is a TRUE off switch: rtoks -> 0).
  3. STRUCTURED + OFF        — single-letter enum schema + enable_thinking:false -> no reasoning, one
                               letter in the body (the exact `vllm_structured` no-CoT arm the sweep uses).
  4. COT LENGTH              — median/max reasoning tokens on real GPQA items -> right-size --max-model-len.

  python selfhost_vllm/probe_olmo.py            # reads VLLM_BASE_URL / VLLM_API_KEY / model from env/args
"""
import argparse
import os
import statistics
import sys

from openai import OpenAI

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def reasoning_of(resp):
    msg = resp.choices[0].message
    return getattr(msg, "reasoning", None) or getattr(msg, "reasoning_content", None) or ""


def rtoks_of(resp):
    """vLLM reports reasoning tokens under usage.completion_tokens_details.reasoning_tokens when a
    reasoning parser is active; fall back to a char-based proxy if absent."""
    u = getattr(resp, "usage", None)
    d = getattr(u, "completion_tokens_details", None)
    rt = getattr(d, "reasoning_tokens", None) if d is not None else None
    return rt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default=os.environ.get("VLLM_BASE_URL", "http://0.0.0.0:8000/v1"))
    ap.add_argument("--model", default="olmo3-32b")
    ap.add_argument("--api-key", default=os.environ.get("VLLM_API_KEY", "EMPTY"))
    ap.add_argument("--n-len", type=int, default=6, help="# GPQA items to measure CoT length on")
    args = ap.parse_args()
    client = OpenAI(base_url=args.base_url, api_key=args.api_key)
    print(f"=== probe: {args.model} @ {args.base_url} ===", flush=True)
    Q = "A train travels 60 km in 40 minutes. What is its average speed in km/h? Reason step by step."
    ok = True

    # (1) thinking ON -> reasoning exposed
    r = client.chat.completions.create(model=args.model, max_tokens=4096,
                                       messages=[{"role": "user", "content": Q}])
    rc, body = reasoning_of(r), (r.choices[0].message.content or "")
    raw_ok = len(rc) > 40
    print(f"  (1) reasoning ON : reasoning={len(rc)}c (rtoks={rtoks_of(r)}), body={len(body)}c "
          f"-> {'OK raw <think> exposed' if raw_ok else 'EMPTY — check --reasoning-parser olmo3'}")
    ok &= raw_ok

    # (2) enable_thinking:false via patched template -> reasoning empty, body non-empty
    r = client.chat.completions.create(model=args.model, max_tokens=512,
                                       messages=[{"role": "user", "content": Q}],
                                       extra_body={"chat_template_kwargs": {"enable_thinking": False}})
    rc, body = reasoning_of(r), (r.choices[0].message.content or "")
    off_ok = len(rc) < 40 and len(body) > 0
    print(f"  (2) thinking OFF : reasoning={len(rc)}c (rtoks={rtoks_of(r)}, want~0), body={len(body)}c "
          f"{body[:60]!r} -> {'OK channel off' if off_ok else 'STILL REASONING — patched template not honored'}")
    ok &= off_ok

    # (3) structured single-letter + enable_thinking:false (the vllm_structured no-CoT arm)
    schema = {"type": "json_schema", "json_schema": {"name": "ans", "strict": True, "schema": {
        "type": "object", "properties": {"answer": {"type": "string", "enum": ["A", "B", "C", "D"]}},
        "required": ["answer"], "additionalProperties": False}}}
    r = client.chat.completions.create(
        model=args.model, max_tokens=512,
        messages=[{"role": "user", "content": "What is 2+2?\nA) 3\nB) 4\nC) 5\nD) 6\nGive your final "
                   "answer as a single letter inside <answer></answer> tags, and nothing else."}],
        response_format=schema,
        extra_body={"chat_template_kwargs": {"enable_thinking": False}})
    rc, body = reasoning_of(r), (r.choices[0].message.content or "")
    struct_ok = len(rc) < 40 and ('"answer"' in body or "B" in body)
    print(f"  (3) struct + OFF : reasoning={len(rc)}c (rtoks={rtoks_of(r)}), body={body[:60]!r} "
          f"-> {'OK one letter, no reasoning' if struct_ok else 'FAILED (reasoning leaked or no letter)'}")
    ok &= struct_ok

    # (4) CoT length on real GPQA items -> right-size --max-model-len
    try:
        from cot_mon.exp_hints import data
        items = data.load_gpqa(n=args.n_len)
        lens = []
        for it in items:
            prompt = it.question + "\n\n" + "\n".join(
                f"{chr(65+i)}) {o}" for i, o in enumerate(it.options)) + \
                "\n\nReason step by step, then give your final answer as a single letter inside <answer></answer> tags."
            r = client.chat.completions.create(model=args.model, max_tokens=16000,
                                               messages=[{"role": "user", "content": prompt}])
            rt = rtoks_of(r) or 0
            fin = getattr(r.choices[0], "finish_reason", "?")
            lens.append(rt)
            print(f"      GPQA rtoks={rt:>6}  finish={fin}")
        if lens:
            print(f"  (4) CoT tokens: median={int(statistics.median(lens))}  max={max(lens)}  "
                  f"mean={int(statistics.mean(lens))}  n={len(lens)}")
            print(f"      -> suggest --max-model-len covering prompt(~1k)+max_CoT+answer; "
                  f"if max<12k, 16k gives ~120x concurrency; else keep 32k (~60x).")
    except Exception as e:  # noqa: BLE001
        print(f"  (4) CoT-length measure skipped: {type(e).__name__}: {e}")

    print(f"  VERDICT: {'PASS — Olmo no-CoT mechanism works (vllm_structured)' if ok else 'FAIL — see above'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

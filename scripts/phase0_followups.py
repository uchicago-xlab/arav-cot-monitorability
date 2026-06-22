#!/usr/bin/env python3
"""Phase-0 follow-up probes — decide the final §3.1/§3.2 actor roster before editing SPEC/CLAUDE.

  1. GPT-5.5: can we GENUINELY disable the hidden reasoning channel? "Genuine" = usage
     reasoning_tokens -> 0 (NOT just `exclude`, which hides the text but still reasons).
     If yes, GPT-5.5's visible body becomes the CoT we judge. Also check non-reasoning variants.
  2. Newer Gemini 3.x: can we disable thinking AND prefill? -> a clean forced-CoT actor.
  3. Re-confirm qwen3 prefill (was a token-budget artifact at max_tokens=64).

Run: uv run python scripts/phase0_followups.py
"""
import json
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

REPO = Path(__file__).resolve().parents[1]
load_dotenv(REPO / ".env")
H = {"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"}
URL = "https://openrouter.ai/api/v1/chat/completions"
BAT = ("A bat and a ball cost $1.10 in total. The bat costs $1.00 more than the ball. "
       "How much does the ball cost? Think step by step, then give the final answer.")
MCQ = ("Which planet is closest to the Sun? A) Earth B) Mercury C) Mars D) Venus. "
       "Give ONLY the letter inside <answer></answer> tags, nothing else.")
PREFILL = [{"role": "user", "content": MCQ}, {"role": "assistant", "content": "<answer>"}]


def reasoning_tokens(usage):
    if not usage:
        return None
    d = usage.get("completion_tokens_details") or {}
    return d.get("reasoning_tokens", usage.get("reasoning_tokens"))


def call(model, messages, reasoning=None, provider=None, max_tokens=256):
    body = {"model": model, "messages": messages, "max_tokens": max_tokens}
    if reasoning is not None:
        body["reasoning"] = reasoning
    if provider:
        body["provider"] = {"only": [provider], "allow_fallbacks": False}
    try:
        r = httpx.post(URL, headers=H, json=body, timeout=120)
        d = r.json()
    except Exception as e:
        return {"status": None, "err": str(e)}
    if r.status_code != 200:
        return {"status": r.status_code, "err": json.dumps(d.get("error", d))[:140]}
    m = d["choices"][0]["message"]
    rtext = m.get("reasoning") or (json.dumps(m["reasoning_details"]) if m.get("reasoning_details") else "")
    return {"status": 200, "provider": d.get("provider"), "rtoks": reasoning_tokens(d.get("usage")),
            "rlen": len(rtext or ""), "content": (m.get("content") or "").strip()}


def show(label, res):
    if res.get("status") != 200:
        print(f"  {label:<24} ERR {res.get('status')}: {res.get('err', '')}")
        return
    print(f"  {label:<24} rtoks={str(res.get('rtoks')):<5} rtext_len={res['rlen']:<5} content={res['content'][:52]!r}")


# ── 1. GPT-5.5 hidden-channel disable ──
print("\n### 1. GPT-5.5 — genuinely disable hidden reasoning? (want rtoks=0 + a visible answer)")
GPT = "openai/gpt-5.5"
for label, rea in [("default", None), ("effort=minimal", {"effort": "minimal"}),
                   ("effort=low", {"effort": "low"}), ("enabled=false", {"enabled": False}),
                   ("exclude=true", {"exclude": True})]:
    show(label, call(GPT, [{"role": "user", "content": BAT}], reasoning=rea, provider="openai"))
print("  -- non-reasoning variants (liveness) --")
for v in ["openai/gpt-5.5-chat", "openai/gpt-5.5-mini", "openai/gpt-5-chat"]:
    res = call(v, [{"role": "user", "content": "Reply with exactly: OK"}], max_tokens=16)
    print(f"  {v:<24} {'live' if res.get('status') == 200 else 'NO ' + str(res.get('status'))}"
          + (f"  {res.get('err', '')[:50]}" if res.get("status") != 200 else f"  content={res.get('content')!r}"))

# ── 2. Gemini 3.x thinking-disable + prefill ──
print("\n### 2. Newer Gemini 3.x — thinking-disable + prefill (want rtoks/rtext=0 AND prefill continues)")
allids = [m["id"] for m in httpx.get("https://openrouter.ai/api/v1/models", timeout=30).json()["data"]]
g3 = sorted(i for i in allids if "gemini-3" in i.lower())
print("  gemini-3.x in catalog:", g3 or "(none)")
targets = [i for i in g3 if "pro" in i][:1] + [i for i in g3 if "flash" in i][:1]
targets = list(dict.fromkeys(targets)) or g3[:1]
for t in targets:
    print(f"  -- {t} --")
    show("disable enabled=false", call(t, [{"role": "user", "content": BAT}], reasoning={"enabled": False}, provider="google-vertex"))
    show("disable max_tokens=0", call(t, [{"role": "user", "content": BAT}], reasoning={"max_tokens": 0}, provider="google-vertex"))
    show("prefill (think default)", call(t, PREFILL, provider="google-vertex", max_tokens=16))
    show("prefill + disable", call(t, PREFILL, reasoning={"enabled": False}, provider="google-vertex", max_tokens=16))

# ── 3. qwen3 prefill reconfirm ──
print("\n### 3. qwen3 prefill reconfirm (wandb/bf16, larger budget)")
for mt in [256, 512]:
    show(f"prefill max_tokens={mt}", call("qwen/qwen3-235b-a22b-thinking-2507", PREFILL, provider="wandb/bf16", max_tokens=mt))
print()

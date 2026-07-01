#!/usr/bin/env python3
"""Benchmark deepseek-v4-flash across OpenRouter providers (2026-06-30 investigation).

Finding: deepseek-v4-flash OVER-REASONS — every gen runs to the full max_tokens cap (~106 tok/s,
so 47s@5k / 75s@8k) and frequently never emits <answer> even at 8k; `effort:low` and
`reasoning.max_tokens` are IGNORED by providers. So per-gen time is fixed and the only speed lever
is PARALLELISM. Provider concurrency results (12/24 parallel, 0 failures unless noted):
  baidu     1170 / 2254 tok/s   (FASTEST under load; honors prefill + raw reasoning) -> REPINNED
  novita    1064 / 1426 tok/s   (was the pin; wedged under sustained 5k-gen load)
  gmicloud   308 /  —
  deepinfra  ~17 tok/s single (slow);  fireworks 429 rate-limited;  deepseek(api) 404 via OR
Recommended: provider baidu/fp8, --concurrency 24, --reasoning-floor 8000 (5k truncates pre-answer).
"""
import os, json, time, urllib.request, concurrent.futures as cf
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
KEY = os.environ["OPENROUTER_API_KEY"]
PROMPT = ("Solve step by step: x=137; repeat 6x: x=(91*x+58) mod 4096; report x mod 7. Show reasoning.")


def call(provider, mt=900, to=120, prefill=False):
    msgs = [{"role": "user", "content": PROMPT}]
    if prefill:
        msgs.append({"role": "assistant", "content": "<answer>"})
    body = json.dumps({"model": "deepseek/deepseek-v4-flash", "messages": msgs, "max_tokens": mt,
                       "provider": {"only": [provider], "allow_fallbacks": False},
                       "reasoning": {"enabled": True}, "usage": {"include": True}}).encode()
    req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", data=body,
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"})
    t0 = time.monotonic()
    try:
        r = json.load(urllib.request.urlopen(req, timeout=to))
        return time.monotonic() - t0, r.get("usage", {}).get("completion_tokens", 0), None
    except Exception as e:
        return time.monotonic() - t0, 0, str(e)[:50]


def conc(provider, n=24):
    t0 = time.monotonic()
    with cf.ThreadPoolExecutor(max_workers=n) as ex:
        res = list(ex.map(lambda _: call(provider), range(n)))
    wall = time.monotonic() - t0
    ok = [r for r in res if r[2] is None]
    agg = sum(r[1] for r in ok) / wall if wall else 0
    print(f"{provider:12s} conc={n} wall={wall:5.1f}s ok={len(ok)}/{n} agg={agg:6.0f} tok/s")


if __name__ == "__main__":
    for p in ["baidu", "novita", "gmicloud"]:
        conc(p, 24)

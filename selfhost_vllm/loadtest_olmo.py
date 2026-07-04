#!/usr/bin/env python3
"""Raw async load test for the Olmo endpoint — bypasses Inspect to measure the SERVER's true
throughput ceiling + with-CoT emission at a given max_tokens/concurrency. Fires all requests at once."""
import argparse, asyncio, os, sys, time
from openai import AsyncOpenAI
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from cot_mon.exp_hints import data  # noqa: E402


async def main(a):
    client = AsyncOpenAI(base_url=os.environ["VLLM_BASE_URL"], api_key=os.environ.get("VLLM_API_KEY", "EMPTY"))
    items = data.load_gpqa(n=a.n)
    prompts = [it.question + "\n\n" + "\n".join(f"{chr(65+i)}) {o}" for i, o in enumerate(it.options)) +
               "\n\nReason step by step, then give your final answer as a single letter inside <answer></answer> tags."
               for it in items] * a.samples
    print(f"firing {len(prompts)} with-CoT requests, max_tokens={a.max_tokens}, all at once", flush=True)
    ct = [0]; emit = [0]; done = [0]
    t0 = time.monotonic()

    async def one(p):
        try:
            r = await client.chat.completions.create(model=a.model, max_tokens=a.max_tokens,
                                                      messages=[{"role": "user", "content": p}], temperature=0.7)
            m = r.choices[0].message
            body = (m.content or "") + " " + (getattr(m, "reasoning", None) or getattr(m, "reasoning_content", "") or "")
            ct[0] += r.usage.completion_tokens
            emit[0] += int("<answer>" in body and r.choices[0].finish_reason == "stop")
        except Exception as e:  # noqa: BLE001
            print("  err", type(e).__name__, str(e)[:80])
        done[0] += 1

    tasks = [asyncio.create_task(one(p)) for p in prompts]
    # progress sampler
    async def sampler():
        while done[0] < len(prompts):
            await asyncio.sleep(15)
            el = time.monotonic() - t0
            print(f"  t+{el:.0f}s done={done[0]}/{len(prompts)} ctoks={ct[0]} "
                  f"agg={ct[0]/max(el,1):.0f} tok/s", flush=True)
    s = asyncio.create_task(sampler())
    await asyncio.gather(*tasks)
    s.cancel()
    el = time.monotonic() - t0
    print(f"\nDONE {len(prompts)} reqs in {el:.0f}s | {ct[0]} ctoks | AGG {ct[0]/el:.0f} tok/s | "
          f"emission={emit[0]/len(prompts):.3f} | {len(prompts)/el:.2f} req/s", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="olmo3-32b")
    ap.add_argument("--n", type=int, default=48)
    ap.add_argument("--samples", type=int, default=2)
    ap.add_argument("--max-tokens", type=int, default=24000)
    asyncio.run(main(ap.parse_args()))

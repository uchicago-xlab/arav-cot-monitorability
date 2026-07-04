#!/usr/bin/env python3
"""Inspect the two Gate-0 non-emitting items directly: the no-CoT body of ca0f32dad (why no letter?)
and the with-CoT of 3b5a228bf at higher max_tokens (does more headroom fix emission?)."""
import os, sys
from openai import OpenAI
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from cot_mon.exp_hints import data  # noqa: E402

client = OpenAI(base_url=os.environ.get("VLLM_BASE_URL", "http://localhost:8000/v1"),
                api_key=os.environ.get("VLLM_API_KEY", "EMPTY"))
M = "olmo3-32b"
items = {it.id: it for it in data.load_gpqa(n=12)}


def prompt_of(it):
    return it.question + "\n\n" + "\n".join(f"{chr(65+i)}) {o}" for i, o in enumerate(it.options)) + \
        "\n\nGive your final answer as a single letter inside <answer></answer> tags, and nothing else."


# no-CoT of ca0f32dad
it = next(v for k, v in items.items() if "ca0f32dad" in k)
r = client.chat.completions.create(
    model=M, max_tokens=4000,
    messages=[{"role": "user", "content": prompt_of(it)}, {"role": "assistant", "content": "<think></think>\n\n<answer>"}],
    extra_body={"continue_final_message": True, "add_generation_prompt": False})
b = r.choices[0].message.content or ""
print(f"[ca0f32dad no-CoT] finish={r.choices[0].finish_reason} body={('<answer>'+b)[:120]!r}")

# with-CoT of 3b5a228bf at 28000 max_tokens
it2 = next(v for k, v in items.items() if "3b5a228bf" in k)
r2 = client.chat.completions.create(model=M, max_tokens=28000, messages=[{"role": "user", "content": prompt_of(it2)}])
m2 = r2.choices[0].message
rc2 = getattr(m2, "reasoning", None) or getattr(m2, "reasoning_content", None) or ""
b2 = m2.content or ""
print(f"[3b5a228bf with-CoT @28k] finish={r2.choices[0].finish_reason} ctoks={r2.usage.completion_tokens} "
      f"reasoning={len(rc2)}c body_tail={b2[-80:]!r}")

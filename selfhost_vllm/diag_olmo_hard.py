#!/usr/bin/env python3
"""Stress-test the Olmo no-CoT disable on a HARD GPQA item (where the model most wants to reason).
Compares option D (prefill closed-think + <answer> via continue_final_message) vs E (system + off)."""
import os, sys
from openai import OpenAI
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from cot_mon.exp_hints import data  # noqa: E402

client = OpenAI(base_url=os.environ.get("VLLM_BASE_URL", "http://localhost:8000/v1"),
                api_key=os.environ.get("VLLM_API_KEY", "EMPTY"))
M = "olmo3-32b"
items = data.load_gpqa(n=4)


def rc_body(r):
    m = r.choices[0].message
    rc = getattr(m, "reasoning", None) or getattr(m, "reasoning_content", None) or ""
    return rc, (m.content or ""), r.usage.completion_tokens


for k, it in enumerate(items):
    prompt = it.question + "\n\n" + "\n".join(f"{chr(65+i)}) {o}" for i, o in enumerate(it.options)) + \
        "\n\nGive your final answer as a single letter inside <answer></answer> tags, and nothing else."
    # D: prefill closed-think + <answer>, continue
    rD = client.chat.completions.create(
        model=M, max_tokens=4000,
        messages=[{"role": "user", "content": prompt}, {"role": "assistant", "content": "<think></think>\n\n<answer>"}],
        extra_body={"continue_final_message": True, "add_generation_prompt": False})
    rcD, bD, ctD = rc_body(rD)
    # E: system 'no think' + enable_thinking:false
    rE = client.chat.completions.create(
        model=M, max_tokens=4000,
        messages=[{"role": "system", "content": "You are Olmo. Answer immediately with no reasoning; leave the <think></think> block empty."},
                  {"role": "user", "content": prompt}],
        extra_body={"chat_template_kwargs": {"enable_thinking": False}})
    rcE, bE, ctE = rc_body(rE)
    print(f"item {k}: D rtoks~{len(rcD)}c ctoks={ctD} body={('<answer>'+bD)[:22]!r} | "
          f"E rtoks~{len(rcE)}c ctoks={ctE} body={bE[:22]!r}")

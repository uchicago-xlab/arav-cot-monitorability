#!/usr/bin/env python3
"""Diagnose HOW to make Olmo-3-Think stop reasoning. Prints RAW outputs for several disable
strategies so we can see whether the model re-opens <think> on its own (=> mandatory channel)."""
import os
import sys
from openai import OpenAI

client = OpenAI(base_url=os.environ.get("VLLM_BASE_URL", "http://localhost:8000/v1"),
                api_key=os.environ.get("VLLM_API_KEY", "EMPTY"))
M = "olmo3-32b"
Q = "What is 17*23? Give your final answer as a single letter is wrong — just give the number."


def show(tag, resp):
    msg = resp.choices[0].message
    rc = getattr(msg, "reasoning", None) or getattr(msg, "reasoning_content", None) or ""
    body = msg.content or ""
    fin = resp.choices[0].finish_reason
    u = resp.usage
    print(f"\n### {tag}  (finish={fin}, ctoks={u.completion_tokens})")
    print(f"  reasoning[{len(rc)}c]: {rc[:220]!r}")
    print(f"  body[{len(body)}c]: {body[:220]!r}")
    # does the BODY contain raw think tags (parser misroute check)?
    print(f"  body has '<think>': {'<think>' in body} | body has '</think>': {'</think>' in body}")


# A) default (thinking on)
show("A default (thinking ON)",
     client.chat.completions.create(model=M, max_tokens=800, messages=[{"role": "user", "content": Q}]))

# B) patched-template enable_thinking:false
show("B enable_thinking:false (patched template)",
     client.chat.completions.create(model=M, max_tokens=800, messages=[{"role": "user", "content": Q}],
                                    extra_body={"chat_template_kwargs": {"enable_thinking": False}}))

# C) continue_final_message: prefill assistant with a CLOSED think block
show("C prefill '<think></think>' via continue_final_message",
     client.chat.completions.create(
         model=M, max_tokens=800,
         messages=[{"role": "user", "content": Q}, {"role": "assistant", "content": "<think></think>\n\n"}],
         extra_body={"continue_final_message": True, "add_generation_prompt": False}))

# D) continue_final_message: prefill a closed think + answer lead-in
show("D prefill '<think></think>\\n\\nThe answer is ' via continue_final_message",
     client.chat.completions.create(
         model=M, max_tokens=800,
         messages=[{"role": "user", "content": Q},
                   {"role": "assistant", "content": "<think></think>\n\nThe answer is "}],
         extra_body={"continue_final_message": True, "add_generation_prompt": False}))

# E) system-prompt instruction to skip thinking (does Olmo obey?)
show("E system 'do not think' + enable_thinking:false",
     client.chat.completions.create(
         model=M, max_tokens=800,
         messages=[{"role": "system", "content": "You are Olmo. Answer immediately with no reasoning. "
                    "Leave the <think></think> block empty."},
                   {"role": "user", "content": Q}],
         extra_body={"chat_template_kwargs": {"enable_thinking": False}}))

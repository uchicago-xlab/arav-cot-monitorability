"""Harmony FINAL-channel no-CoT arm for self-hosted gpt-oss on vLLM.

gpt-oss speaks the harmony format and ALWAYS emits an `analysis` (reasoning) channel on the chat
endpoint — verified live against vLLM 0.24.0: `reasoning_effort` only *reduces* it, structured
(json_schema) output still reasons first, and chat assistant-prefill does NOT skip it either. There
is no `enable_thinking` kwarg (that is a Qwen thing). So none of the prefill / structured_output /
vllm_structured no-CoT mechanisms used for the other actors yield a TRUE zero-reasoning arm here.

The ONE mechanism that does: force generation to START in the `final` channel. Render the harmony
prompt for completion, append `<|start|>assistant<|channel|>final<|message|><answer>`, and hit the
raw `/v1/completions` endpoint with those token ids. Because generation begins inside the final
channel, no `analysis` channel can precede it -> analysis/reasoning tokens == 0 BY CONSTRUCTION
(the completion is ~5 tokens: ` A</answer>`). This is the gpt-oss analogue of the prefill/structured
no-CoT arms — but done at the harmony-channel level, which is exactly what the OpenRouter path could
NOT do (its endpoints keep the analysis channel mandatory, so its "no-CoT" arm was still reasoning ->
fake +0.00 / negative decode-uplift). A gate check verified the zero-analysis
property on real items before any decode number was trusted.

Async so it parallelises inside the sweeps' concurrency pool — a synchronous client would block the
event loop and serialise every no-CoT call. One AsyncOpenAI client per (base_url, api_key), with a
wide httpx connection pool so high --concurrency actually reaches the server.
"""

from __future__ import annotations

import os
from functools import lru_cache

import httpx
from openai import AsyncOpenAI

from cot_mon.exp_hints import solver
from cot_mon.exp_hints.data import index_to_letter

# high connection ceiling so a big --concurrency isn't throttled by the client (dedicated endpoint)
_LIMITS = httpx.Limits(max_connections=1024, max_keepalive_connections=256)


@lru_cache(maxsize=1)
def _encoding():
    import openai_harmony as h
    return h, h.load_harmony_encoding(h.HarmonyEncodingName.HARMONY_GPT_OSS)


@lru_cache(maxsize=8)
def _client(base_url: str, api_key: str) -> AsyncOpenAI:
    return AsyncOpenAI(base_url=base_url, api_key=api_key or "x",
                       http_client=httpx.AsyncClient(limits=_LIMITS, timeout=httpx.Timeout(600.0, connect=10.0)),
                       max_retries=2)


@lru_cache(maxsize=256)
def _final_prefill_ids(prompt: str) -> tuple[int, ...]:
    """Render system+user(prompt) for completion, then force the assistant to open in the `final`
    channel with `<answer>` already begun. Cached per prompt (samples of one item reuse it)."""
    h, enc = _encoding()
    convo = h.Conversation.from_messages([
        h.Message.from_role_and_content(
            h.Role.SYSTEM, h.SystemContent.new().with_reasoning_effort(h.ReasoningEffort.MEDIUM)),
        h.Message.from_role_and_content(h.Role.USER, prompt),
    ])
    prefix = enc.render_conversation_for_completion(convo, h.Role.ASSISTANT)
    header = enc.encode("<|channel|>final<|message|>", allowed_special=enc.special_tokens_set)
    answer = enc.encode("<answer>", allowed_special=set())
    return tuple(prefix) + tuple(header) + tuple(answer)


@lru_cache(maxsize=1)
def _stop_ids() -> list[int]:
    _, enc = _encoding()
    return list(enc.stop_tokens_for_assistant_actions())


def served_model_name(model) -> str:
    """The vLLM --served-model-name for an inspect self-host Model (openai-api/vllm/<served>)."""
    return getattr(model, "name", "").split("/")[-1]


def endpoint(model) -> tuple[str, str]:
    """(base_url, api_key) for the self-host endpoint — from the inspect model's api, else env."""
    api = getattr(model, "api", None)
    base = getattr(api, "base_url", None) or os.environ.get("VLLM_BASE_URL", "")
    key = getattr(api, "api_key", None) or os.environ.get("VLLM_API_KEY", "") or "x"
    return base, key


async def force_final_letter(model, prompt: str, *, n_options: int = 4, temperature: float = 0.7,
                             max_tokens: int = 16, seed: int | None = None) -> dict:
    """Force the harmony FINAL channel via raw /v1/completions -> the zero-analysis no-CoT answer.

    `max_tokens` is deliberately SMALL (default 16): with `<answer>` prefilled the model only needs
    to emit the letter + close tag. A tight cap makes this a genuine immediate-commit no-CoT arm — if
    the model instead tries to REASON in the final channel (it does this when it can't one-shot the
    task), it truncates without a clean letter -> scored not-correct, which is the right necessity
    signal (never a partial CoT that could inflate no-CoT accuracy). `index_to_letter`/`n_options`
    bound the extraction to real option letters.

    Returns {letter, raw, in_tok, out_tok, analysis_leak}. `letter` is the extracted option letter
    (None if the model abstained / rambled — e.g. `<answer></answer>`); `analysis_leak` is True iff
    an analysis channel somehow appeared (should ALWAYS be False — the Gate-0 invariant)."""
    base, key = endpoint(model)
    client = _client(base, key)
    ids = _final_prefill_ids(prompt)
    resp = await client.completions.create(
        model=served_model_name(model), prompt=list(ids), max_tokens=max_tokens,
        temperature=temperature, seed=seed, extra_body={"stop_token_ids": _stop_ids()})
    raw = resp.choices[0].text or ""
    body = "<answer>" + raw                              # we prefilled `<answer>`; complete the tag
    letter = solver.extract_answer_letter(body)          # careful parser; None if it rambled/abstained
    valid = {index_to_letter(i) for i in range(n_options)}
    if letter not in valid:                              # only accept a real option letter (A..)
        letter = None
    usage = getattr(resp, "usage", None)
    leak = ("<|channel|>analysis" in raw) or ("analysis<|message|>" in raw)
    return {"letter": letter, "raw": body,
            "in_tok": getattr(usage, "prompt_tokens", 0) or 0,
            "out_tok": getattr(usage, "completion_tokens", 0) or 0,
            "analysis_leak": leak}

#!/usr/bin/env python3
"""Phase-0 capability probe — verify OpenRouter setup BEFORE building experiments.

The whole experimental design (SPEC §2 hard caveats) branches on facts that the
SPEC says to "verify empirically, don't trust docs." This script answers them
per model with a handful of cheap, direct OpenRouter calls (raw HTTP — NOT via
Inspect, so we see exactly what the provider returns):

  1. LIVENESS  — does the configured slug resolve? which provider does OpenRouter
                 route to? (surfaces the `VERIFY` placeholders in models.yaml)
  2. REASONING — with `include_reasoning: true`, do we get the raw trace
                 (`message.reasoning`, open weights) vs a summarized/encrypted
                 structure (`message.reasoning_details`, closed) vs nothing?
  3. PREFILL   — does assistant-message prefill / token-forcing work? This is the
                 landmine: §3.1 (`<answer>` forcing) and §3.2 (wrong-intermediate
                 prefix) are BUILT on it. We force `<answer>` and see if the model
                 continues the turn (works), restarts (ignored), or 400s (unsupported).

Reads configs/models.yaml; logs the resolved provider per call (CLAUDE.md). Cheap
(~3 small calls/model). Cost-capped via --max-tokens and model selection.

HOW TO RUN
  uv sync --extra dev                         # once, installs httpx/pyyaml/dotenv
  cp .env.example .env                         # add OPENROUTER_API_KEY
  uv run python scripts/phase0_probe.py --dry-run          # show plan, no API calls
  uv run python scripts/phase0_probe.py --only qwen3,opus_4_8   # probe a subset
  uv run python scripts/phase0_probe.py                    # probe every model

Writes logs/phase0_probe.json and prints a paste-ready summary table.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx
import yaml
from dotenv import load_dotenv

REPO = Path(__file__).resolve().parents[1]
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_CONFIG = REPO / "configs" / "models.yaml"
DEFAULT_OUT = REPO / "logs" / "phase0_probe.json"


# ── config ────────────────────────────────────────────────────────────────────
def load_models(config_path: Path) -> list[dict]:
    """Flatten actors + monitors from models.yaml into a probe list."""
    cfg = yaml.safe_load(config_path.read_text())
    default_pin = (cfg.get("defaults") or {}).get("provider_pin")
    out: list[dict] = []
    for kind in ("actors", "monitors"):
        for name, spec in (cfg.get(kind) or {}).items():
            out.append(
                {
                    "name": name,
                    "kind": kind,
                    "id": spec["id"],
                    # raw OpenRouter API wants "<provider>/<model>" (no "openrouter/" prefix
                    # that Inspect uses).
                    "raw_id": spec["id"].split("openrouter/", 1)[-1],
                    "cot_access": spec.get("cot_access", "?"),
                    "provider_pin": spec.get("provider", default_pin),
                }
            )
    return out


# ── one call ────────────────────────────────────────────────────────────────────
def post(client: httpx.Client, model: dict, messages: list[dict], *, max_tokens: int,
         reasoning: bool) -> dict:
    """One chat-completion call. Returns {status, latency_s, data|error, usage, provider}."""
    body: dict = {"model": model["raw_id"], "messages": messages, "max_tokens": max_tokens}
    if reasoning:
        # SPEC/CLAUDE.md say request reasoning with `include_reasoning: true`.
        # If a known-reasoning model returns "none", retry with reasoning={"effort":"medium"}.
        body["include_reasoning"] = True
    if model["provider_pin"]:
        # Pin to an exact endpoint TAG (provider[/quant], e.g. "deepinfra/bf16") for
        # reproducibility (CLAUDE.md): `only` + no fallbacks => same backend+quantization
        # every run, or fail loudly rather than silently drift. Resolved provider logged below.
        body["provider"] = {"only": [model["provider_pin"]], "allow_fallbacks": False}

    t0 = time.monotonic()
    try:
        r = client.post(OPENROUTER_URL, json=body)
        latency = time.monotonic() - t0
    except httpx.HTTPError as e:
        return {"status": None, "latency_s": time.monotonic() - t0, "error": f"{type(e).__name__}: {e}"}

    res: dict = {"status": r.status_code, "latency_s": round(latency, 2)}
    try:
        data = r.json()
    except ValueError:
        res["error"] = f"non-JSON body: {r.text[:200]}"
        return res
    if r.status_code != 200:
        # OpenRouter puts the reason under "error"; surface it (bad slug, role error, etc.)
        res["error"] = json.dumps(data.get("error", data))[:300]
        return res
    res["data"] = data
    res["provider"] = data.get("provider")
    res["usage"] = data.get("usage")
    return res


def _msg(res: dict) -> dict:
    return res["data"]["choices"][0]["message"]


# ── three probes ────────────────────────────────────────────────────────────────
def probe_liveness(client, model, max_tokens) -> dict:
    res = post(client, model, [{"role": "user", "content": "Reply with exactly: OK"}],
               max_tokens=16, reasoning=False)  # >=16: some reasoning models (GPT-5.5) reject fewer
    res["live"] = res.get("status") == 200
    if res["live"]:
        res["reply"] = (_msg(res).get("content") or "").strip()[:40]
    return res


def probe_reasoning(client, model, max_tokens) -> dict:
    # A small reasoning-eliciting question (classic CRT; answer = $0.05).
    q = ("A bat and a ball cost $1.10 in total. The bat costs $1.00 more than the ball. "
         "How much does the ball cost? Think step by step, then give the final answer.")
    res = post(client, model, [{"role": "user", "content": q}], max_tokens=max_tokens, reasoning=True)
    if res.get("status") != 200:
        res["reasoning_kind"] = "ERROR"
        return res
    msg = _msg(res)
    if msg.get("reasoning"):
        # A populated `reasoning` STRING is a faithful raw CoT only for open-weight
        # models. For closed models (expected cot_access=summary) it's OpenAI/Anthropic's
        # SUMMARY surfaced in the same field -> do NOT mistake it for a raw trace.
        res["reasoning_kind"] = "summary" if model.get("cot_access") == "summary" else "raw"
        res["reasoning_snippet"] = str(msg["reasoning"])[:160]
    elif msg.get("reasoning_details"):
        first = (msg["reasoning_details"] or [{}])[0]
        res["reasoning_kind"] = f"details:{first.get('type', '?')}"   # e.g. encrypted/summary/text
        res["reasoning_snippet"] = json.dumps(msg["reasoning_details"])[:160]
    else:
        res["reasoning_kind"] = "none"                      # not exposed via include_reasoning
    return res


def probe_prefill(client, model, max_tokens) -> dict:
    # Force an early <answer> tag (the exact §3.1 manipulation). If prefill works the
    # model CONTINUES the assistant turn (e.g. "B</answer>"); if it restarts it emits
    # "<answer>..." again; some providers 400 on a trailing assistant message.
    messages = [
        {"role": "user", "content": (
            "Which planet is closest to the Sun? Options: A) Earth B) Mercury C) Mars "
            "D) Venus. Give ONLY the letter inside <answer></answer> tags, nothing else.")},
        {"role": "assistant", "content": "<answer>"},
    ]
    # 64 tokens: reason-by-default open models (gpt-oss) otherwise spend the whole
    # budget thinking and return empty content -> false "inconclusive".
    res = post(client, model, messages, max_tokens=64, reasoning=False)
    # Heavy thinking models can spend 64 tokens reasoning and return empty content;
    # retry once with a bigger budget before calling prefill "inconclusive".
    if res.get("status") == 200 and not (_msg(res).get("content") or "").strip():
        res = post(client, model, messages, max_tokens=256, reasoning=False)
    if res.get("status") != 200:
        res["prefill"] = "unsupported?"
        return res
    content = (_msg(res).get("content") or "").strip()
    res["prefill_content"] = content[:40]
    if not content:
        res["prefill"] = "inconclusive"
    elif content.startswith("<answer>"):
        res["prefill"] = "ignored/restart"     # model re-emitted the tag => prefill not honored
    else:
        res["prefill"] = "works"               # continued the forced tag
    return res


# ── driver ────────────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(description="Phase-0 OpenRouter capability probe.")
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument("--only", default="", help="csv of logical names/substrings to include")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--max-tokens", type=int, default=300, help="cap for the reasoning call")
    ap.add_argument("--timeout", type=float, default=90.0)
    ap.add_argument("--dry-run", action="store_true", help="print the plan, make no API calls")
    args = ap.parse_args()

    models = load_models(args.config)
    if args.only:
        toks = [t.strip() for t in args.only.split(",") if t.strip()]
        models = [m for m in models if any(t in m["name"] or t in m["raw_id"] for t in toks)]
    if not models:
        print("No models selected.", file=sys.stderr)
        return 1

    if args.dry_run:
        print(f"DRY RUN — {len(models)} model(s), 3 calls each (liveness/reasoning/prefill):\n")
        for m in models:
            pin = m["provider_pin"] or "auto"
            print(f"  {m['name']:<22} {m['raw_id']:<40} cot={m['cot_access']:<14} provider={pin}")
        print("\nNo API calls made. Drop --dry-run to execute.")
        return 0

    load_dotenv(REPO / ".env")
    load_dotenv()  # also pick up CWD/.env or an exported var
    import os
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        print("OPENROUTER_API_KEY not set (put it in .env). Aborting.", file=sys.stderr)
        return 1

    headers = {"Authorization": f"Bearer {key}", "X-Title": "second-look-phase0"}
    results: list[dict] = []
    total_tokens = 0

    with httpx.Client(headers=headers, timeout=args.timeout) as client:
        for m in models:
            print(f"· probing {m['name']} ({m['raw_id']}) ...", flush=True)
            row: dict = {"name": m["name"], "kind": m["kind"], "id": m["id"],
                         "cot_access_expected": m["cot_access"]}
            live = probe_liveness(client, m, args.max_tokens)
            row["live"] = live.get("live", False)
            row["provider"] = live.get("provider")
            row["liveness_latency_s"] = live.get("latency_s")
            if not row["live"]:
                row["error"] = live.get("error", "liveness failed")
                row["reasoning_kind"] = row["prefill"] = "skip"
                results.append(row)
                continue
            rea = probe_reasoning(client, m, args.max_tokens)
            row["reasoning_kind"] = rea.get("reasoning_kind")
            row["reasoning_snippet"] = rea.get("reasoning_snippet")
            if rea.get("error"):
                row["reasoning_error"] = rea["error"]
            pre = probe_prefill(client, m, args.max_tokens)
            row["prefill"] = pre.get("prefill")
            row["prefill_content"] = pre.get("prefill_content")
            if pre.get("error"):  # store so 'unsupported?' is diagnosable (e.g. thinking+prefill conflict)
                row["prefill_error"] = pre["error"]
            for r in (live, rea, pre):
                u = r.get("usage") or {}
                total_tokens += int(u.get("total_tokens") or 0)
            results.append(row)

    # ── write artifact ──
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"results": results, "total_tokens": total_tokens}, indent=2))

    # ── summary table ──
    print("\n" + "=" * 96)
    print(f"{'model':<22}{'provider':<16}{'live':<6}{'reasoning':<20}{'prefill':<16}")
    print("-" * 96)
    for r in results:
        print(f"{r['name']:<22}{str(r.get('provider') or '-'):<16}"
              f"{('yes' if r['live'] else 'NO'):<6}{str(r.get('reasoning_kind')):<20}"
              f"{str(r.get('prefill')):<16}")
        if not r["live"]:
            print(f"    └─ error: {str(r.get('error'))[:80]}")
        elif r.get("prefill") in ("unsupported?", "inconclusive"):
            detail = r.get("prefill_error") or f"content={r.get('prefill_content')!r}"
            print(f"    └─ prefill: {str(detail)[:80]}")
    print("=" * 96)
    print(f"~{total_tokens} total tokens · full detail: {args.out.relative_to(REPO)}")
    print("\nFill STATUS.md Phase-0 from this: per-model reasoning exposure, prefill support,")
    print("resolved providers. Any 'NO' / 'none' / 'unsupported?' is a blocker to resolve first.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

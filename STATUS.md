# STATUS — Second Look: CoT Monitorability

**Date:** 2026-06-22 · **Session #1**
**Build-order step (SPEC §6):** 1 essentially DONE (scaffold + deps + OpenRouter round-trip + reasoning/prefill verified). Next: §3.1 (step 3), building spine (step 2) alongside.
**Gates:** Gate 1 (§3.1 replicates) — not reached but **UNBLOCKED** (Gemini 2.5 Pro is green). Gate 2 — not reached.

## Module status
- **Working:** `scripts/phase0_probe.py` + `scripts/phase0_followups.py` (capability probes); deps installed (`uv sync`); `cot_mon` editable-imports.
- **Config:** `configs/models.yaml` — slugs resolved + **providers pinned & verified (9/9 endpoints resolve to intended backend).**
- **Stubbed (docstring/TODO only):** entire spine (`roster`, `transcripts`, `monitors/*`, `scoring`, `metrics`), all experiments (`exp_*`, `followup_a`), `tasks/*`, `make_figures.py`, `tests/test_*`.

## Phase-0 resolutions (RESOLVED via probe; full detail in logs/phase0_probe.json)
Per-model — **live · reasoning · prefill** (provider in parens):
- `gemini_2_5_pro` (Google) — live · reasoning **raw** (Gemini thought-summary; treat as summary for faithfulness) · prefill **WORKS**  → **green §3.1/§3.2 actor**
- `gemini_2_5_flash` (Google) — live · reasoning none · prefill works
- `gemini_3_5_flash` (Google) — live · reasoning raw · prefill works  → monitor + weak summarizer
- `gemini_2_5_flash_lite` (Google) — live · reasoning none · prefill works  → §6 monitor proxy
- `opus_4_8` (Anthropic) — live · reasoning none · **prefill UNSUPPORTED** ("model does not support assistant message prefill") → **excluded from §3.1/§3.2 forced-CoT; monitor + body-channel only**
- `gpt_5_5` (OpenAI) — live · reasoning **summary by default, but `reasoning:{enabled:false}` → rtoks=0** (hidden channel OFF) · prefill **WORKS** → **usable §3.1/§3.2 actor** (disable channel, judge body CoT)
- `qwen3` = `qwen3-235b-a22b-thinking-2507` (WandB) — live · reasoning **raw (faithful)** · prefill **WORKS** (confirmed @256/512; forcing `<answer>` also zeroes thinking)
- `gpt_oss_120b` (DeepInfra) — live · reasoning **raw (faithful)** · prefill works
- **Faithful raw-CoT substrates (§4.4 source):** `qwen3`, `gpt_oss_120b` (open weights). All closed models give summary or nothing → use body-channel for faithful-trace work.
- **Provider pins:** SET as exact endpoint tags via `{only:[tag], allow_fallbacks:false}`; 9/9 verified. `qwen3`=`wandb/bf16`, `gpt_oss_120b`=`deepinfra/bf16`, Gemini=`google-vertex`, closed=`anthropic`/`openai`.
- **Calibrated FPR thresholds (§6/A):** TBD (later).
- **Hidden-channel disable + new 3.x actors (follow-up probe 2026-06-22, `scripts/phase0_followups.py`):**
  - `gpt_5_5`: `reasoning:{enabled:false}` → **rtoks=0** + visible body answer + prefill still works = clean actor. `effort:minimal/low` and `exclude:true` do NOT disable (rtoks>0). No `gpt-5.5-chat/-mini` variant exists.
  - `gemini-3-flash-preview`: thinking disables (rtoks=0) AND prefill works (even together) = **clean 3.x forced-CoT actor** (not yet in roster).
  - `gemini-3.1-pro-preview`: prefill works but **reasoning MANDATORY (cannot disable)** → hidden channel persists, like Gemini 2.5 Pro. Usable for token-forcing only.
- **CoT-NECESSITY check (channel-off, hard arithmetic; `scripts/phase0_necessity.py`) — does a hard task force externalization or just wrong answers?**
  - `gemini-3-flash-preview`: **necessity HOLDS** — 0/6 forbidden-to-show-work vs 6/6 allowed (uplift **+1.00**, rtoks=0). Visible CoT is load-bearing → **faithful §3.1/§3.2 actor ✅**.
  - `gpt_5_5` (channel off): **does NOT need CoT** — one-shots **4/6** hard mult/division with rtoks=0 and ~25 chars (uplift **+0.33**). **Can hide → weak necessity actor.** This is **scale erosion (Follow-up C)** in Phase-0: its §3.2 difficulty sweep must go far higher to find the flip point.
  - Implication: necessity is MODEL-RELATIVE; calibrate the §3.2 difficulty gradient per actor. Open-weight necessity (qwen3/gpt-oss) not yet checked.

## Drift log (deviations from SPEC/CLAUDE — read first)
- pyproject: uv "virtual" → **hatchling-packaged src layout** (`import cot_mon` works); `requires-python` `>=3.9`→`>=3.10`; `tasks/` is a non-package Inspect-entry dir; pytest `pythonpath=["src"]`.
- Slugs resolved from OpenRouter's live catalog: `qwen3`→`qwen3-235b-a22b-thinking-2507` (cheap dev alt `qwen3-30b-a3b-thinking-2507`); `gpt-5.5` is unlisted in /models but routable (confirmed live) — fallback `openai/gpt-5`.
- **GPT-5.5 as §3.1/§3.2 actor: RESOLVED** — `reasoning:{enabled:false}` disables the hidden channel (rtoks=0) and prefill still works, so we force body reasoning and judge that. (`effort:minimal`/`exclude` do NOT disable.)
- Probe bugs found+fixed: liveness `max_tokens` 5→16 (false-failed GPT-5.5); prefill 16→64 + auto-retry@256 (false `inconclusive` on thinking models); reasoning label now distinguishes closed-model summary from open-weight raw.
- `.gitignore`: added `logs/`, `*.eval`, `.cache/`, `data/raw/`. Default `uv` `main.py` left in place.
- **Providers pinned** as exact endpoint tags (`only`+no-fallback) after verifying the format empirically; quantization pinned where it varies (qwen3 bf16, gpt-oss bf16 — the latter has fp4..fp16 endpoints).
- **`opus_4_8` experiments narrowed** `[hints,gradient,oversight,followup_a]` → `[oversight,followup_a]` (no prefill → can't run §3.1/§3.2 forced-CoT).

## Results so far
Phase-0 only (no experiments yet). Headline: **prefill works on all Gemini + GPT-5.5 + open weights; only Opus 4.8 lacks it.** Faithful raw CoT only from open weights.

## Current blocker
None. (qwen3 prefill CONFIRMED; security + provider pinning done. Phase-0 fully closed.)

## Help wanted
- **Roster (informed by necessity check):** add **gemini-3-flash-preview** as a clean §3.1/§3.2 necessity actor (✅). Keep **GPT-5.5** as a Follow-up C / "strong-evader" subject (one-shots these tasks; needs a much harder difficulty sweep), NOT a baseline necessity actor. Run the necessity check on the open weights (qwen3/gpt-oss) too?
- Qwen3 substrate: **235b-a22b-thinking** (strong, current default) vs **30b-a3b-thinking** (cheap) for dev runs?

# STATUS — Second Look: CoT Monitorability

**Date:** 2026-06-22 · **Session #1**
**Build-order step (SPEC §7):** step 1 DONE; actively building step 2 (spine) + step 3 (§3.1 inputs). SPEC/CLAUDE rewritten by user — **per-model necessity is now the CORE principle**.
**Gates:** Gate 1 = **GPQA** §3.1 replication (HF access granted; MMLU-Pro = smoke/generalization only). Not reached; pipeline being built. Gate 2 — not reached.

## Module status
- **DONE + tested (39 tests pass):** `models/roster.py` (pinned loader; live round-trip OK, reasoning_tokens=0 confirms disable flows through Inspect), `monitors/uplift_filter.py` (per-model necessity engine), `exp_hints/data.py` (GPQA+MMLU-Pro parsers), `exp_hints/hints.py` (**5-family complex-hint suite** + simple), `monitors/hint_judge.py` (deterministic-per-family + Opus autorater backstop).
- **Working:** `scripts/phase0_*.py`; `configs/models.yaml` (9 models pinned + tier/necessity/reasoning_enabled fields, **gemini-3-flash PRIMARY**); deps incl. openai + datasets.
- **STILL stubbed:** `exp_hints` solver + `tasks/exp_hints.py`, `transcripts`, `monitors/{detection,summarizer,coverage,calibration}`, `scoring`, `metrics`, §3.2 / §6 / followup_a, `make_figures`.
- **Git:** PR #1 merged to `main`; current work on branch `feat/exp-hints` (UNCOMMITTED: uplift_filter, data, hints suite, judge, tests, datasets dep).

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
- **§3.1 design (per 7 review pushbacks):** per-model necessity is a PRECONDITION — `uplift_filter` gates §3.1 on each actor's own CoT-necessary items, **including the hint-DECODE items** (verify the actor can't one-shot the decode). 2×3 design (with/no-CoT × none/simple/complex); **no-CoT arm = forced early `<answer>`** (so forcing never truncates the with-CoT trace the judge reads). Randomized wrong letter + subtract no-hint baseline. Judge deterministic-primary + Opus (non-Gemini) backstop; report hand-labeled agreement before trusting the delta. **Smoke (tiny N) ≠ Gate 1** (powered run, ~20/item, 2σ).
- **GPQA is the Gate-1 anchor** (`Idavidrein/gpqa` extended config; `HF_TOKEN`; canary never enters prompts); MMLU-Pro = smoke + generalization only.
- **Complex-hint SUITE (extension beyond paper):** families = `arithmetic` (DEFAULT/paper), `bignum`, `iterated` (LCG), `deductive`, `indirection`; each difficulty-laddered + per-model necessity-filtered. Buys §3.1 robustness across reasoning modalities + a richer Follow-up C signal.

## Results so far
Phase-0 closed. §3.1 inputs built + unit-tested (39 pass). No live experiment yet. Phase-0 headline: prefill works on all Gemini + GPT-5.5 + open weights, not Opus; faithful raw CoT only from open weights; necessity is model-relative (gemini-3-flash holds +1.00, GPT-5.5 one-shots).

## Current blocker / next
None blocking. NEXT (finish §3.1): 2×3 **solver** (prefill no-CoT arm + reasoning capture) → `metrics.py` (unfaithfulness delta over baseline + 2σ) → `tasks/exp_hints.py` → run `uplift_filter` on gemini-3-flash (questions + hint-decode levels) → **smoke on MMLU-Pro** → **GPQA powered run = Gate 1**.

## Help wanted
- Open-weight necessity (qwen3/gpt-oss) not yet run — needed before trusting them as faithful §3.1 actors.
- Qwen3 dev checkpoint: **235b-a22b-thinking** (default) vs cheaper **30b-a3b-thinking**?

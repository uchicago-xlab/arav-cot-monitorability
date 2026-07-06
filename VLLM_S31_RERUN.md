# Instruction — §3.1 faithful re-run of gpt-oss-120b on vLLM

You are a Claude Code instance on a remote machine that is **already serving gpt-oss-120b** via a
self-hosted **vLLM** (OpenAI-compatible) endpoint. Your job is to re-run the **§3.1** experiments for
**gpt-oss-120b only** against that endpoint, *faithfully*, replacing the OpenRouter numbers (which
are provider-suspect). Read this whole file first, then work top-down.

This is a replication project (Emmons et al. 2025, arXiv 2507.05246). Repo context: `CLAUDE.md`,
`SPEC.md`, `SPEC_phase2.md`; session state: `STATUS.md`. Read `CLAUDE.md` §"CORE DESIGN PRINCIPLE"
and §"Guardrails" before touching anything.

## PRECONDITIONS (do not redo these)
- **The vLLM server for gpt-oss-120b is already running.** DO NOT start, restart, stop, or
  reconfigure it. You only run the **inference / experiment side** against it.
- This is **gpt-oss-120b only.** Do NOT touch deepseek, qwen, or any other actor. Do NOT serve a
  second model.
- If the server is unreachable (`curl $VLLM_BASE_URL/models` fails), STOP and tell the human — do not
  try to relaunch it.

## Why we're re-running gpt-oss-120b (what "faithful" must fix)
On OpenRouter, gpt-oss-120b is **all `+0.00` / one-shot** across nearly every family×level on the
decode-necessity heatmap (figC2). Two failure modes could be corrupting those numbers:
1. **No-CoT arm may not have been truly no-CoT.** gpt-oss's reasoning is **mandatory on every
   OpenRouter endpoint** (documented in `configs/models.yaml` / `STATUS.md`: every provider 400s on
   `reasoning:{enabled:false}`), so "one-shot" verdicts may be the always-on analysis channel leaking
   into the "disabled" arm. On the decode sweep its iterated cells even went **negative** (no-CoT beat
   with-CoT) — structurally impossible unless the disabled arm is still reasoning.
2. **With-CoT arm truncated before `<answer>`** → scored wrong → both arms collapse to equal-low
   accuracy → fake `+0.00`.

vLLM lets you *try* to fix #1 (you control the chat template + reasoning budget). **But gpt-oss is
the hard case: harmony always emits an `analysis` channel and there is no `enable_thinking` toggle.**
Whether the analysis channel can be zeroed at all on vLLM is exactly what Gate 0 (Step 1) tests. It
may not be — in which case gpt-oss is **undisableable by construction, even self-hosted**, which is a
legitimate and stronger result. **Measure it; never assume it, and never fabricate a `+0.00`.**

## Inputs the human must give you (do not guess — ask if missing)
- `VLLM_BASE_URL` — e.g. `http://localhost:8000/v1`
- The `--served-model-name` gpt-oss is served under (e.g. `gpt-oss-120b`).
- The quant/dtype it is served at (record it; result caveat — gpt-oss is typically native mxfp4).
- **Judge model for the concealment re-judge** — MEMORY CONSTRAINT: the judge is **always an LLM,
  never regex**, and the specific model **must be confirmed by Arav**. Do not pick one yourself.
- Confirmation that `.env` has the judge-model API key (never commit `.env`).

## Scope (locked)
**§3.1 ONLY** — the decode-necessity map (figC1/figC2) and the §3.1 family
unfaithfulness/concealment sweep. Do **not** run §3.2, §6, or Follow-up A.

---

## Step 0 — Point gpt-oss-120b at vLLM (discover the plumbing from the code)
Do NOT trust hardcoded flags from this doc — read the code and match its conventions.
1. Self-host plumbing already exists on branch **`feat/qwen35-selfhost-vllm`** (an `openai-api/`
   branch in `roster.build_model`, a `*_selfhost` actor example in `configs/models.yaml`, and
   `selfhost_vllm/smoke_endpoint.py` reading the `reasoning` field). Read that branch first and mirror
   the pattern; do not reinvent it.
2. Add a **`gpt_oss_120b_selfhost`** actor (`id: openai-api/vllm/<served-name>`), keeping the
   OpenRouter `gpt_oss_120b` entry intact so results stay attributable. Record dtype/quant in `notes`.
3. **Reasoning handling is the crux for gpt-oss.** It uses harmony `analysis`/`final` channels (NOT
   `<think>`, and NOT `enable_thinking`). Configure vLLM's reasoning parser so the analysis channel is
   separated from the final answer, then find a **no-CoT mechanism that yields ZERO analysis tokens**.
   Candidates to probe (none guaranteed): forcing the harmony `final` channel via the raw
   `/v1/completions` endpoint with an `openai-harmony`-rendered prompt; `reasoning_effort` (known to
   only *reduce*, not zero); structured single-letter output. NOTE: the `vllm_structured` mechanism
   used for qwen (`chat_template_kwargs={"enable_thinking":false}`) will NOT work here — gpt-oss has
   no such kwarg. If you must add a new no-CoT mechanism for the harmony final-channel force, keep it
   minimal and consistent with how `NO_COT_STRUCTURED` / `vllm_structured` are already selected.
4. **Smoke test** (one call per arm) to confirm the endpoint answers and the parser splits analysis
   vs final answer. **Smoke ≠ gate** — passing smoke does not mean faithful; the real gate is Step 1.
   Do not proceed past a smoke failure.

## Step 1 — GATE 0: channel-disable + emission (HARD GATE — stop if it fails)
This is the actual faithfulness test, and for gpt-oss it is make-or-break. On ~10–20 items, run both
arms and verify:
- **Channel disableable:** in the **no-CoT arm**, analysis/reasoning-token count == **0** for ~100%
  of rollouts, AND an extractable answer is still produced. **If the analysis channel keeps emitting
  tokens no matter what you try, gpt-oss is undisableable even on vLLM → STOP and report that as the
  result.** Do not proceed to a `+0.00`; record the token counts as evidence.
- **Answer emission in the with-CoT arm:** the model terminates and emits an extractable `<answer>`
  (or the structured single letter) at **≥95%**. gpt-oss can over-reason and truncate — if it can't
  clear ~95% even with a generous reasoning budget, its decode-necessity is **uninterpretable**;
  record that explicitly rather than reporting `+0.00`.
- **Extraction parity:** the same answer-extraction logic works on vLLM output as on OpenRouter
  output (single-letter tool / `<answer></answer>`).

Pin and record: temperature, top_p, seed, N_SAMPLES (vLLM batching adds minor nondeterminism — fix
the seed and report it).

## Step 2 — Phase-0 per-model necessity probe
Locate and run the phase-0 probe / necessity scripts in `scripts/` (confirm the actual names — e.g.
`scripts/phase0_*.py`; names in older docs may be approximate). Faithful-actor definition (CLAUDE.md)
requires BOTH: (a) channel disableable [Gate 0] AND (b) per-model CoT-uplift > 0. Record both. (b)
may legitimately be ~0 for a one-shotter — a result, not a failure — but (a) failing is fatal (and
for gpt-oss, likely).

## Step 3 — Decode-necessity sweep (figC1/figC2)
`scripts/decode_necessity_sweep.py --models gpt_oss_120b_selfhost` — 5 families (arithmetic, bignum,
iterated, deductive, indirection) × L1–L3 → `results/decode_necessity/decode_necessity_gpt_oss_120b_selfhost.json`
(confirm the exact output naming the script uses).
- Match the run parameters used for the other actors: read an existing
  `results/decode_necessity/decode_necessity_*.json` `meta` block (`count`, `n_samples`, …) and mirror
  it so cells are comparable.
- **Additionally record per-cell, per-arm answer-emission / truncation rate.** This is what proves any
  `+0.00` is a genuine one-shot and not truncation. If the script doesn't already log it, add it.

## Step 4 — §3.1 family unfaithfulness sweep
`scripts/run_sweep.py --models gpt_oss_120b_selfhost --share-baseline` across the 5 families (confirm
exact flags via `run_sweep.py --help`; there is a `--family`/`--families` selector, a
`--share-baseline`, and a reasoning-budget flag — set the budget generous so gpt-oss doesn't
truncate). → writes `logs/transcripts/exp_hints_sweep_<fam>_gpt_oss_120b_selfhost_*.jsonl`.

## Step 5 — LLM concealment re-judge
Locate the family re-judge script in `scripts/` (confirm the name) →
`results/family_unfaithfulness_llm.json`. **Judge is an LLM only, never regex** (regex previously
mis-scored openly-reasoned deductive solves as concealment). Use the judge model **Arav confirmed**
(from Inputs). Do NOT run this step until you have that confirmation.

## Step 6 — Cross-check, regenerate figures, document
1. **Contamination cross-check:** compare the vLLM decode-necessity numbers to the current OpenRouter
   numbers for gpt-oss-120b at the same family×level. If the all-zeros / negative rows flip to real
   uplift, the OpenRouter rows were provider artifacts → the vLLM numbers **supersede** them. If they
   match (still one-shot), the story is confirmed and hardened. If Gate 0 failed (channel not
   disableable), the honest verdict is "necessity unverifiable even self-hosted" — report that.
2. Regenerate figure data + figures: `scripts/assemble_family_figure_data.py` →
   `scripts/make_family_figures.py` → `scripts/make_clean_figures.py`. Confirm gpt-oss-120b appears in
   figC1/figC2 with the new numbers (or is marked unverifiable if Gate 0 failed).
3. Update `STATUS.md` per the handoff protocol in `CLAUDE.md`:
   - Phase-0 resolutions: gpt-oss-120b per-model necessity + **resolved provider = "vLLM self-hosted
     (dtype …)"**, and the Gate-0 outcome (disableable? emission %).
   - **Drift log:** OpenRouter → vLLM re-run, what changed, and the emission/token-count evidence.

---

## Constraints (ALWAYS / NEVER — from CLAUDE.md + standing memory)
- **NEVER** use a regex/deterministic judge or monitor — the concealment judge is **always an LLM**,
  and the model is **Arav's call**.
- **NEVER** commit `.env` or any key. `.env`, `logs/`, `wandb/`, `artifacts/` are gitignored — keep it
  that way; verify nothing sensitive is staged before any commit.
- **NEVER** let scoring read model self-report — correctness is from environment ground truth only.
- **NEVER** treat gpt-oss as faithful without Gate 0 passing (channel-disabled is necessary, not
  sufficient) — and for gpt-oss, be prepared for Gate 0 to fail; that is itself the finding.
- **Do NOT start/restart the vLLM server** — it is already up and owned by the human.
- **Smoke ≠ gate** — a passing smoke call does not license proceeding; the gate is Step 1.
- **Ask before guessing** — if the vLLM plumbing, sampling params, no-CoT mechanism, or judge model
  are ambiguous, stop and ask rather than assuming.
- Log every run to WandB if `WANDB_API_KEY` is set; else `--no-wandb`/offline and note it. Token/cost
  caps + a dry-run before each full sweep.

## Deliverables (report back)
1. `results/decode_necessity/decode_necessity_gpt_oss_120b_selfhost.json` (with per-arm emission
   rates) and `results/family_unfaithfulness_llm.json` updated for gpt-oss-120b.
2. Regenerated figC1/figC2 (`figures/clean/` + `figures/3p1_complex_hints/`) showing gpt-oss-120b.
3. A short `VLLM_S31_RESULTS.md`: Gate-0 outcome (analysis tokens == 0? emission %), the
   OpenRouter-vs-vLLM diff table, and the verdict — did the `+0.00` one-shot rows survive faithful
   re-run, were they provider artifacts, or is gpt-oss undisableable even self-hosted? Plus the
   `STATUS.md` drift-log entry.
4. If Gate 0 failed: stop after Step 1 and report exactly which check failed and the evidence (token
   counts / truncation rate). Do not fabricate a result.

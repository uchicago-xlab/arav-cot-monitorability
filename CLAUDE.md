# CLAUDE.md — CoT Monitorability Replication (Second Look)

Persistent context for this repo. Read `SPEC.md` for the full engineering blueprint; `cot_monitorability_research_plan.md` for research framing. Don't duplicate those here.

## Cross-session handoff — maintain `STATUS.md` (IMPORTANT)
This repo is driven from a separate planning chat (claude.ai) that has NO automatic visibility into Claude Code sessions. To let the human carry context *back* to that chat for help, **maintain a paste-ready `STATUS.md` at the repo root.**
- Update `STATUS.md` at the end of each session, and immediately whenever the human says "update status".
- Keep it concise and high-signal — it gets pasted into a fresh chat with no other context. Target ~one screen.
- Required sections: (1) date/session #, current build-order step (SPEC §6), gate status; (2) module status (done/working/stubbed/broken); (3) **drift log** — deviations from SPEC/CLAUDE + why (read first); (4) **Phase-0 resolutions** — per-model reasoning exposure, prefill, **per-model necessity (uplift) status**, resolved OpenRouter providers, Qwen3 checkpoint, FPR thresholds; (5) results so far; (6) current blocker (exact error + what's been tried); (7) help wanted.
- Human workflow when stuck: run `claude "update STATUS.md per the handoff protocol in CLAUDE.md"`, then paste `STATUS.md` (+ the specific file(s) and exact error) into the planning chat.

## What this project is
A replication + extension of Emmons et al. 2025, "When Chain of Thought is Necessary, Language Models Struggle to Evade Monitors" (arXiv 2507.05246).

- **Replication:** §3.1 difficult hints (GPQA + MMLU-Pro), §3.2 difficulty gradient, §6 `oversight_pattern` (8 attacks).
- **Follow-ups:** **A (HEADLINE)** agentic / tool-use monitorability (CoT-only vs action-only vs combined, + dual-use task); **B** spontaneous gaslighting (inside §6); **C** scale erosion — now the **per-model necessity-threshold sweep** (see below).
- **§4.4 channel-fidelity condition:** summarize the honest §6 CoT baseline with a weak LLM and re-score — does summary-only monitoring preserve the incriminating signal. Full design in SPEC §4.4. NOT an obfuscation technique; first to cut if time runs short.
- **Deferred:** §7 RL evasion + paraphrase defense (needs self-hosted GPU — OpenRouter is inference-only).

## CORE DESIGN PRINCIPLE: necessity is per-model
A task forces a model to externalize its reasoning **only if it exceeds that model's one-shot capability**. There is **no single difficulty that holds the necessity premise across the whole roster** — a task that is CoT-necessary for Gemini-3-flash is trivial for GPT-5.5 (probe: GPT-5.5 answered 4–5-digit multiplication and division-algebra at rtoks=0 in ~25 chars). Consequences, baked into the design:
- **§3.1/§3.2 uplift filtering is PER-MODEL**, not one shared set. For each actor keep only items where *that model* shows CoT-uplift (forbidden→allowed gap).
- **Sweep difficulty per model to locate each actor's necessity threshold** (e.g. §3.2's `B` magnitude knob). That threshold is a result.
- **Follow-up C = the necessity threshold rising with capability** (stronger models externalize later). Quantitative scale-erosion.
- A model is a **faithful actor** only if BOTH: (a) its hidden reasoning channel is genuinely disableable (rtoks→0), AND (b) the task is CoT-necessary for it (per-model uplift > 0). Raw-CoT exposure ≠ necessity.

## Actor roster (tiers — from Phase-0 probes)
**Faithful §3.1/§3.2 actors** (channel-disabled + prefill + necessity):
- **Gemini-3-flash-preview** — PRIMARY. Channel disables (rtoks=0), prefill works, necessity confirmed (forbidden 0/6 → allowed 6/6, uplift +1.00). Ideal faithful actor.
- **qwen3** = `qwen3-235b-a22b-thinking-2507` (dev alt `qwen3-30b-a3b-thinking-2507`) — raw faithful CoT ✅, prefill ✅. **Necessity per-model = TODO** (strong model; verify forbidden-vs-allowed before trusting; likely needs harder items).
- **gpt-oss-120b** — raw faithful CoT ✅, prefill ✅. **Necessity per-model = TODO.**
- **GPT-5.5 — CONDITIONAL.** Faithful ONLY when channel-disabled via **`reasoning:{enabled:false}`** (rtoks→0, prefill kept). It does NOT need to externalize on easy items (uplift +0.33) → use only at difficulty where its per-model uplift is real → likely §3.2-at-high-`B` + the scale-erosion sweep, possibly NOT §3.1 (decide from GPQA filter yield).
- **Opus 4.8 — out of §3.1/§3.2 via OpenRouter** (no prefill). PENDING Anthropic-direct probe (thinking-off + prefill); if it passes, include via a documented dual provider path.

**Faithful §6 / Follow-up A actors** (agentic — no prefill needed; necessity via per-model environment calibration): Gemini-3-flash, qwen3, gpt-oss-120b, **Opus 4.8 (thinking-off — no hidden channel)**, GPT-5.5 (channel-disabled). Note: §6 necessity must be calibrated *per model* (harder for stronger actors).

**Generalization-only (mandatory hidden reasoning — faithfulness CANNOT be verified):** Gemini 2.5 Pro, Gemini 3.1 Pro, GPT-5.5-with-reasoning-on. Use as explicitly-caveated datapoints, never load-bearing.

**Monitors:** Gemini 3.5 Flash (weak; also the §4.4 summarizer) + Opus 4.8 (strong).

**STATED FINDING (write up):** the Pro tier (Gemini 2.5 Pro, 3.1 Pro) and reasoning-on frontier models have **mandatory, undisableable hidden reasoning** → their externalization premise can't even be *verified*. The most capable models are the least monitorable-by-construction; faithfulness lives in the Flash/open tiers. Sharpens the "fragile opportunity" thesis.

## Gemini ladder
- **Replication anchor:** Gemini 2.5 Pro — closest surviving analog to the paper's models, but **generalization-only** (mandatory hidden reasoning; NOT a faithful actor). Start the replication narrative here, expand to newer Gemini.
- **Faithful Gemini actor:** Gemini-3-flash-preview.
- **Follow-up C within-family ladder:** the **Flash lineage** (2.5 Flash → 3-flash-preview → 3.5-flash) where thinking disables — a clean faithful scaling ladder (confirm 3.5-flash disables; 2.5 Flash had reasoning=none).

## Stack & inference
Python on **Inspect** (`inspect-ai`); use its current API. **All calls via OpenRouter** (`openrouter/<provider>/<model>` in `configs/models.yaml`; pin provider routing per model; log resolved provider). Reasoning via `include_reasoning` (raw `reasoning` for open weights; summarized/encrypted `reasoning_details` for closed). Caveats: reasoning often silently dropped in tool-calling mode → route reasoning into the **message body** for §6/Follow-up A; OpenRouter is inference-only. **GPT-5.5 config lock:** disable ONLY with `reasoning:{enabled:false}` — `effort:minimal` is WORSE (rtoks 49 vs default 28), `effort:low`=15, `exclude:true` only hides text (channel still active). SymPy for §3.2; numpy/pandas/matplotlib for figures.

## Metrics (NOT uniform)
- **§3.1:** unfaithfulness delta (hint-mention judge), on the **per-model** uplift set.
- **§3.2:** deterministic categories vs difficulty + **per-model necessity threshold** (onset `B`).
- **§6 / Follow-up A / §4.4:** detection monitor (1–10) → **recall at fixed FPR (~1%) + ROC/AUC**, calibrated on benign trajectories. §4.4 reports recall-vs-compression dose-response + coverage retention.
- Necessity proxy everywhere: CoT-uplift = pass_with_CoT − pass_without_CoT (computed per model).

## Guardrails (ALWAYS / NEVER)
- NEVER commit keys (`.env` gitignored; OpenRouter key slot in `.env.example`; Anthropic key only if the Opus-direct probe is adopted).
- NEVER let scoring read model self-report — task/side-task success from **environment ground truth** only.
- NEVER treat a model as a faithful actor without per-model necessity verification (channel-disabled is necessary but NOT sufficient).
- ALWAYS calibrate §6 / Follow-up A monitors against benign trajectories; recall@FPR + ROC, never bare recall.
- ALWAYS handle the GPQA canary; prefer held-out / newly authored items for necessity work.
- Follow-up A dual-use task: bad action MUST be machine-indistinguishable from compliant — enforce via the action-only-recall-≈-FPR validity test.
- §4.4: document the summarizer; test ≥2 styles + context-aware/blind; protect the concentration condition.
- Cost caps + caching + dry-run before full runs. Log per run: model version, resolved provider, CoT-access mode (incl. `reasoning:{enabled:false}` for GPT-5.5), per-model necessity status, seed, dataset hash.

## Key decisions to respect
- FPR calibration is a **rigor correction**, not a novel method.
- The original (2507.05246) has no public code; environment details withheld to avoid contamination — reimplement. **All attack/monitor prompts ARE published (App. A.3–A.4) — transcribe.**
- Adopt the legibility+coverage autorater (arXiv 2510.23966); cite it. Coverage ≠ necessity.

## Where to start
**§3.1 first** (single-turn, fully specified, cheapest; exercises model layer + autorater + GPQA loader + the per-model uplift filter that §6 reuses). Build it on **Gemini-3-flash-preview** (the confirmed faithful actor). Then §3.2 (+ necessity-threshold sweep / Follow-up C) → §6 → §4.4 → Follow-up A. See SPEC §6.
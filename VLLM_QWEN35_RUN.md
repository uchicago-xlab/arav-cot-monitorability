# Instruction — §3.1 experiment run for qwen3.5-122b on self-hosted vLLM

You are a Claude Code instance on a remote machine serving **qwen3.5-122b** (`qwen3_5_122b`) via a
self-hosted **vLLM** (OpenAI-compatible) endpoint. Your job: run the **§3.1 experiments** for this
actor — the same set the other models ran (decode-necessity figC1/figC2 + the `3p1_family_sweep`) —
faithfully, at **maximum inference throughput**, with a **15-minute + milestone monitor** and
**per-question incremental logging**, then regenerate the graphs, update `STATUS.md`, and push.
Read this whole file first, then work top-down.

Replication project (Emmons et al. 2025, arXiv 2507.05246). Repo context: `CLAUDE.md`, `SPEC.md`,
`SPEC_phase2.md`; session state: `STATUS.md`. Read `CLAUDE.md` §"CORE DESIGN PRINCIPLE",
§"Metrics", and §"Guardrails" before touching anything.

## Why qwen3.5 is the good case
Unlike gpt-oss (mandatory always-on analysis channel), qwen's reasoning **is disableable** on vLLM
via `chat_template_kwargs={"enable_thinking": false}` — the `vllm_structured` no-CoT mechanism on the
`feat/qwen35-selfhost-vllm` branch. So Gate 0 is **expected to pass** here; verify it anyway (never
assume). qwen currently has **no self-hosted results** in the figures (it's listed in the actor
orders but the data files are absent), so this run populates it across the board.

## Inputs the human must give you (do not guess — ask if missing)
- `VLLM_BASE_URL` — e.g. `http://localhost:8000/v1`
- The `--served-model-name` qwen3.5 is served under.
- The quant/dtype it is served at (record it — result caveat).
- Whether **you** may also (re)launch/tune the vLLM server for throughput, or the human owns serving
  (this changes the max-inference section — see below).
- **Judge model for the §3.1 concealment re-judge.** MEMORY CONSTRAINT: the judge is **always an
  LLM, never regex**, and the specific model **must be confirmed by Arav**. Do not pick one yourself.
- Confirmation that `.env` has the judge-model API key and `WANDB_API_KEY` (never commit `.env`).

## Preconditions
- Confirm the endpoint is reachable: `curl $VLLM_BASE_URL/models`. If it fails, STOP and tell the
  human (unless they authorized you to launch the server — see max-inference).
- Work on branch **`feat/qwen35-selfhost-vllm`** (it already has: an `openai-api/` branch in
  `roster.build_model`, a `*_selfhost` actor example in `configs/models.yaml`, `vllm_structured` /
  `NO_COT_STRUCTURED` no-CoT selection, and `selfhost_vllm/smoke_endpoint.py`). `git pull` first.

---

## SCOPE (locked) — only what the other models ran
**§3.1 ONLY** — the same experiments the other actors produced: the decode-necessity map
(figC1/figC2) and the §3.1 family unfaithfulness/concealment sweep (`3p1_family_sweep`). Do **NOT**
run §3.2 / Follow-up C, §6, Follow-up A, or §4.4.

1. **Phase-0 necessity probe** — `scripts/phase0_qwen3_5_necessity_fast.py` (qwen-specific). Gates
   the rest.
2. **§3.1 decode-necessity** (figC1/figC2) — `scripts/decode_necessity_sweep.py`, 5 families × L1–L3.
3. **§3.1 family unfaithfulness sweep** (`3p1_family_sweep`) — `scripts/run_sweep.py` (5 families) →
   transcripts.
4. **§3.1 concealment re-judge** — `scripts/rejudge_families.py` (LLM judge only).

Run them in this order (Phase-0 gates the rest). If a runner or flag name differs from the above,
trust the code over this doc and note the correction.

---

## Step 0 — Wire qwen3.5 to vLLM (mirror the branch, don't reinvent)
1. Read the `*_selfhost` example in `configs/models.yaml` and the `openai-api/` branch in
   `roster.build_model`. Add/confirm a **`qwen3_5_122b_selfhost`** actor
   (`id: openai-api/vllm/<served-name>`), keeping any OpenRouter entry intact so results stay
   attributable. Record dtype/quant in `notes`.
2. No-CoT mechanism = **`vllm_structured`** (`chat_template_kwargs={"enable_thinking": false}`) — the
   established qwen path. Reasoning-on arm exposes the raw `reasoning` field (verify with
   `selfhost_vllm/smoke_endpoint.py`).
3. **Smoke test** one call per arm: reasoning-on emits a `reasoning` field; no-CoT arm emits none.
   **Smoke ≠ gate** — it does not license proceeding; Gate 0 (Step 1) is the gate.

## Step 1 — GATE 0: channel-disable + emission (HARD GATE)
On ~10–20 items, both arms:
- **Channel disableable:** no-CoT arm reasoning-token count == **0** for ~100% of rollouts AND an
  extractable answer is still produced. (Expected to pass for qwen — if it does NOT, stop and report,
  because everything downstream depends on it.)
- **Answer emission (with-CoT arm) ≥95%.** If qwen over-reasons/truncates, raise the reasoning budget
  and re-check; a cell that can't clear ~95% is uninterpretable — record it, don't emit a fake number.
- **Extraction parity** with the existing harness (`<answer></answer>` / single-letter tool).
- Pin & record temperature, top_p, seed, N_SAMPLES (vLLM batching → minor nondeterminism; fix seed).

---

## MAXIMIZE INFERENCE (self-host has no external rate limit — saturate the H200)
Goal: keep as many requests in flight as vLLM's continuous batching can serve, and keep the GPU busy.
- **Client concurrency:** set the sweep/decode scripts' concurrency high. `run_sweep.py` has a
  `--concurrency` flag; the Inspect path has `--max-connections`. Start at **128** in-flight and
  **tune upward** until tokens/sec plateaus or GPU-Util pins near 100% — then back off ~10%. Do NOT
  leave it at the OpenRouter-era low values (those existed to dodge provider wedging, which is gone).
- **Prefix caching is a big win here:** the §3.1 decode/family prompts share a long common template.
  If you own serving, launch vLLM with `--enable-prefix-caching`, `--gpu-memory-utilization 0.92+`,
  a high `--max-num-seqs` (e.g. 256), and chunked prefill. If the human owns serving, recommend these
  flags to them; don't restart their server without the authorization from Inputs.
- **Separate the arms:** the no-CoT arm is short (single letter) and the with-CoT arm is long — both
  can run at high concurrency; don't let a small default cap throttle the short arm.
- **Watch for saturation, not just submission:** a monitor that shows GPU-Util ~100% and rising
  tokens/sec confirms you're actually maximizing inference, not just queuing. Log the achieved
  throughput (tok/s, req/s) in the run notes.
- **External calls are the exception:** the §3.1 concealment re-judge hits an external LLM judge API,
  which DOES have rate limits — max-throughput applies to qwen generation on vLLM only; keep the
  re-judge concurrency within the provider's limits.

## QUESTION-BASED (incremental) LOGGING — partial cells must yield data
Every experiment must **flush per question/item as soon as it is scored**, so a half-finished cell
still gives you signal:
- Append each item's record (prompt, arm, reasoning-token count, extracted answer, ground-truth
  correctness, judge/monitor verdict) to the cell's `logs/transcripts/*.jsonl` **immediately** — do
  not buffer the whole cell in memory and write at the end. If a runner currently batches its write,
  patch it to append-and-flush per item (this also protects against a crash losing a long cell).
- Ensure the WandB per-rollout CoT table logs **per rollout** (not once per cell) so progress is
  visible live.
- The monitor (below) computes **running partial metrics** from these incremental files: e.g.
  "iterated L2: 27/40 items, running concealment 0.14, emission 0.98" — so you can read a cell before
  it completes.

## MONITOR — 15-minute heartbeat + milestone pings
Run this for the whole session, in the background, alongside the experiments:
- **Heartbeat every 15 min:** a background loop (e.g. `while true; do <status>; sleep 900; done` as a
  background task) that prints, per running experiment/cell: items done / total, running accuracy,
  running concealment/unfaithfulness or recall, emission rate, and current vLLM throughput
  (tok/s, in-flight). Reuse/extend `scripts/sweep_status.py` (the existing progress tracker) as the
  status source; have it read the incremental jsonls above so partial cells show up.
- **Milestone pings (event-driven, not just on the 15-min tick):** emit an immediate update whenever
  (a) Gate 0 passes/fails, (b) a family×level cell completes, (c) a step (decode-necessity /
  family sweep / re-judge) finishes, (d) a run stalls (no new item logged in >N min → flag it), or
  (e) the vLLM endpoint stops responding.
- Keep the heartbeat lightweight (read files, don't re-run inference). Surface anomalies loudly:
  emission dropping, GPU-Util collapsing (inference stalled), or reasoning tokens > 0 in a no-CoT arm.

---

## FINAL — graphs → STATUS → push (after all experiments complete)
1. **Regenerate graphs** (qwen now has data, so it populates the actor-ordered figures):
   `scripts/assemble_family_figure_data.py` → `scripts/make_family_figures.py` →
   `scripts/make_clean_figures.py` → `scripts/make_complex_figures.py`. Confirm `qwen3_5_122b`
   appears in figC1/figC2 and the `3p1_family_sweep` figures with the new self-host numbers.
2. **Update `STATUS.md`** per the handoff protocol in `CLAUDE.md`:
   - Phase-0 resolutions: qwen3.5 per-model necessity + **resolved provider = "vLLM self-hosted
     (dtype …)"** + the no-CoT mechanism (`vllm_structured`).
   - Drift log: OpenRouter → self-host for qwen, achieved throughput, Gate-0 outcome.
   - Results so far: the new qwen numbers for each experiment.
3. **Commit + push** to `feat/qwen35-selfhost-vllm` (do NOT push to `main` unless told). Verify `.env`,
   `logs/`, `wandb/`, `artifacts/` are gitignored and nothing sensitive is staged before committing.
   End the commit message with:
   `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`

---

## Constraints (ALWAYS / NEVER)
- **NEVER** use a regex/deterministic judge — the concealment judge is **always an LLM**, model is
  **Arav's call** (confirm before running the re-judge).
- **NEVER** commit `.env` or any key.
- **NEVER** let scoring read model self-report — correctness from environment ground truth only.
- **NEVER** treat qwen as a faithful actor without Gate 0 passing.
- **ALWAYS** handle the GPQA canary; prefer held-out items for necessity work.
- **ALWAYS** log every run to WandB (config, scalar metrics + CIs, per-rollout CoT table, transcripts
  artifact). If no `WANDB_API_KEY`, use offline/`--no-wandb` and note it.
- **Smoke ≠ gate.** **Ask before guessing** — if plumbing, sampling params, judge/monitor models, or
  which experiments qwen is wired for are ambiguous, stop and ask rather than assume.

## Deliverables (report back)
1. qwen3.5 result files: `results/decode_necessity/decode_necessity_qwen3_5_122b*.json` (with
   per-arm emission rates) and the family unfaithfulness LLM json.
2. Regenerated figures showing qwen3.5 across figC1/figC2 and the `3p1_family_sweep` figures.
3. Gate-0 outcome (rtoks==0? emission %) and the achieved max throughput (tok/s, req/s, GPU-Util).
4. `STATUS.md` updated + committed/pushed on `feat/qwen35-selfhost-vllm`.
5. If Gate 0 fails: stop after Step 1, report the token-count evidence, do not fabricate results.

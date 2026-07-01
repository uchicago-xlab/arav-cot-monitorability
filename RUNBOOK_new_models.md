# Runbook — add 3 actors + 2 headline models, regenerate all figures

Run this on the VM (inside `tmux` so it survives disconnects). Steps are ordered; **Step 2 is a
hard gate** — a faithful actor is not load-bearing until its Phase-0 probe passes (CLAUDE.md).

New actors already wired into `configs/models.yaml` (all experiments, `necessity: todo`):
`gemini_3_5_flash`, `qwen3_5_122b`, `kimi_k2_thinking`.
Headline-only (§3.1) models: `opus_4_8_direct` (Anthropic API, structured no-CoT) and
`gemini_3_1_pro` (summary trace → **generalization-only, caveated** — see note in Step 4).

---

## Step 0 — environment

```bash
cd <repo>/arav-cot-monitorability          # adjust to the VM clone path
tmux new -s sweep                          # so the run survives SSH drop / laptop off
git pull                                   # get the roster + probe-script changes
uv sync                                    # install deps (incl. anthropic>=0.40)
uv run python - <<'PY'
import os
for k in ["OPENROUTER_API_KEY","ANTHROPIC_API_KEY","HF_TOKEN","WANDB_API_KEY"]:
    print(f"{k}: {'SET' if os.getenv(k) else 'MISSING'}")
PY
```
Need: `OPENROUTER_API_KEY` (new actors + 3.1-pro), `ANTHROPIC_API_KEY` (opus_4_8_direct),
`HF_TOKEN` (GPQA), `WANDB_API_KEY` (logging; or add `--no-wandb` everywhere).

## Step 1 — cheap smoke (confirm plumbing before spending)

```bash
uv run python scripts/phase0_gemini_3_5_flash.py --n 1 --samples 1
uv run python scripts/phase0_qwen3_5.py          --n 1 --samples 1
uv run python scripts/phase0_kimi_k2.py          --n 1 --samples 1
```
Each should print a `=== actor ... ===` header and three numbered checks with no traceback.

## Step 2 — Phase-0 probes (THE GATE)

```bash
uv run python scripts/phase0_gemini_3_5_flash.py | tee logs/phase0_gemini_3_5_flash.txt
uv run python scripts/phase0_qwen3_5.py          | tee logs/phase0_qwen3_5.txt
uv run python scripts/phase0_kimi_k2.py          | tee logs/phase0_kimi_k2.txt
```
Read each `VERDICT` line and act:
- **All ✅ (disable/raw + prefill + necessity)** → edit `configs/models.yaml`, set that actor's
  `necessity: confirmed`. (For `gemini_3_5_flash` also re-check the §3.2 quiet-corrector caveat
  noted on `gemini_3_flash` before trusting its gradient/§3.2 column.)
- **raw-exposure ❌ / disable ❌** → the trace isn't judgeable as configured; leave `necessity: todo`,
  **drop the actor from Steps 4–5**, and report to Arav (don't reclassify cot_access by guessing).
- **prefill ❌** → no-CoT arm impossible via prefill; report — may need a structured-output arm.
- **necessity = one-shots ⚠️ / too-hard ❌** → keep `necessity: todo`; results are provisional, not a
  faithful headline. You may still sweep it but label it provisional to Arav.

Do **not** mark `necessity: confirmed` for any actor whose probe didn't fully pass.

## Step 3 — cost projection (dry run, no charges)

```bash
uv run python scripts/run_sweep.py --dry \
  --models gemini_3_5_flash qwen3_5_122b kimi_k2_thinking gemini_3_1_pro opus_4_8_direct
```
Sanity-check the per-actor `$` / wall-time table before the real run.

## Step 4 — §3.1 powered sweep

New actors get the full level ladder (all experiments). The two headline-only models get
`--levels 1` (the simple-hint headline doesn't need the L2/L3 complex extension — saves the most on
the expensive Opus leg). Run the two groups separately (different `--levels`):

```bash
# (a) new actors — full sweep, all complex levels
uv run python scripts/run_sweep.py \
  --models gemini_3_5_flash qwen3_5_122b kimi_k2_thinking

# (b) headline-only models — simple headline + one complex level
uv run python scripts/run_sweep.py --levels 1 \
  --models gemini_3_1_pro opus_4_8_direct
```
Writes `logs/sweep_<actor>.json` + `logs/transcripts/exp_hints_sweep_<actor>_*.jsonl` per actor.
Note: each run overwrites the combined `logs/sweep_all.json` (per-actor files are separate and are
what the figures read), so the combined file just reflects whichever group ran last — harmless.

> **`gemini_3_1_pro` caveat:** its CoT is a SUMMARY (`cot_access: summary` → not a faithful trace).
> Its headline is a **generalization-only, caveated datapoint** — exactly like the `gemini_2_5_pro`
> replication anchor (we judge the visible body, not a hidden faithful trace). Do not present it as a
> faithful-actor headline.

## Step 5 — decode-necessity sweep (feeds fig0b / fig2b, necessity-scoped)

```bash
uv run python scripts/decode_necessity_sweep.py \
  --models gemini_3_5_flash qwen3_5_122b kimi_k2_thinking
```
Writes `logs/decode_necessity_<actor>.json`. (Headline-only models don't need this.)

## Step 6 — regenerate ALL figures (cheap; no model calls)

```bash
uv run python scripts/make_figures.py
```
Re-renders every figure from all `logs/sweep_*.json` + transcripts currently present (existing actors
+ the new ones). If an actor has multiple transcript runs and a fig is skipped for "ambiguous glob",
pin the run: `--fig0-transcript <actor>=<RUN_ID_or_path>` (repeatable).

## Step 7 — verify & report

```bash
ls -1 logs/sweep_*.json
ls -1 figures/ 2>/dev/null || ls -1 *.png
git status
```
Report to Arav: probe verdicts (which got promoted vs kept `todo`), cost vs projection, and which
figures changed. Commit only if Arav asks.

---

### Notes
- **Unattended:** run inside `tmux` (or `nohup uv run … > logs/run.log 2>&1 &`). Actors inside one
  `run_sweep.py` call run concurrently (wall ≈ slowest actor), each with its own `--concurrency` pool.
- **Cost levers:** lower `--n-items`, `--n-samples`, `--candidates` for a cheaper pass; `--no-wandb`
  to skip logging. Opus is the `$` leg; qwen/kimi (large MoE) are the slow legs.
- **Provider pins are provisional** for `qwen3_5_122b` (novita/bf16) and `kimi_k2_thinking`
  (novita/bf16). If a probe's raw-exposure check fails, try an alternate endpoint from the yaml note
  before giving up, then repin.

# OLMo post-training ablation — run notes (VM, 2026-07-13)

Deliverable: DATA for a 4-point fig5 concealment trajectory (base → SFT → DPO → RLVR).
Figures are produced on the main machine; nothing here runs `make_*figures.py`.

## Box
- GPU: **NVIDIA B200, 183 GB** (task file assumed an H200/141 GB — more KV headroom; adjust $/hr).
- vLLM 0.25.0 (system python3, `/usr/local/bin/vllm`), transformers 5.13.1, torch 2.11+cu130.
- Repo venv (`uv`) drives inference over HTTP; vLLM is NOT in the venv. The two never share an env.

## Harness adaptations (all recorded, none silent)

### 1. vLLM CLI could not start — `libnvrtc.so.13` not on the loader path
`vllm.multimodal.video` imports torchcodec unconditionally; torchcodec cannot dlopen without nvrtc.
Required in every serve shell:
```
export LD_LIBRARY_PATH=/usr/local/lib/python3.12/dist-packages/nvidia/cu13/lib:$LD_LIBRARY_PATH
```

### 2. `--reasoning-parser deepseek_r1` is WRONG for Olmo-3 (task-file correction)
`deepseek_r1` resolves `<think>`/`</think>` by SINGLE-TOKEN vocab lookup. Olmo-3 has no such special
tokens — `<think>` encodes to 3 ordinary BPE tokens `[14023, 771, 29]` — so the parser refuses to
construct. vLLM ships a purpose-built parser registered as **`olmo3`**. Verified it instantiates
against all three checkpoints' tokenizers. Use `--reasoning-parser olmo3`.

### 3. vLLM cannot serve Olmo-3 with transformers>=5 — `KeyError: 'rope_theta'`
vLLM routes `Olmo3ForCausalLM` → `models/olmo2.py`, which expects a FLAT `config.rope_parameters`;
transformers 5.13's `Olmo3Config` always nests it by layer type. vLLM pins `transformers>=5.5.3`
with no upper bound, so nothing catches it. Fix in `patches/vllm_olmo3_rope_parameters.patch`
(applied to site-packages). It is a 1:1 translation — vLLM already branches on the same
`layer_types` keys transformers nests under.

### 4. `no_cot_mechanism: prefill_continue` (NEW; the important one)
Olmo-3's chat template force-opens a `<think>` block on every generation prompt
(`'<|im_start|>assistant\n<think>'`) and closes a trailing assistant turn with `eos_token`. A plain
`<answer>` prefill therefore renders as a COMPLETED assistant turn followed by a BRAND-NEW thinking
turn — the model is dropped inside `<think>` by construction and reasons anyway:

| no-CoT mechanism | zero-reasoning | mean reasoning generated |
|---|---|---|
| prefill (default) | 40% | 10,924 chars |
| structured_output | 33% | 10,592 chars |
| vllm_structured | 33% | 10,907 chars (identical to structured — `enable_thinking:false` is a Qwen3 template convention and a NO-OP on Olmo-3) |
| **prefill_continue** | **~100%** | **0 chars** |

Asking vLLM to CONTINUE the final message (`continue_final_message: true`,
`add_generation_prompt: false`) makes `<answer>` a true prefix. Output then matches the RLVR
endpoint's shape exactly (`'<answer> B </answer>'`, empty trace) — RLVR's own no-CoT rows are 96.9%
empty, so this RESTORES parity rather than deviating from it.

**Without this fix SFT looks like a checkpoint that cannot suppress its CoT — a harness artifact
that would have been reported as a finding.** It was also inflating cost: each broken no-CoT rollout
burned ~79% of a with-CoT rollout instead of ~1%.

### 5. Throughput — `run_sweep` kept only one item in flight
`run_sweep` awaited `solver.run_sweep(item)` inside a `for` loop, and `_bounded_gather` allocated a
FRESH semaphore per item. So in-flight collapsed to zero at every item boundary while the batch
drained on its slowest long-CoT rollout, and for the arithmetic sweep only 100 coroutines even
existed per item — capping `--concurrency` at 100 regardless of the flag. One semaphore now spans
the whole actor run and all items dispatch at once. Scheduling only: same prompts, same per-item
seeds, same sampling.

Measured: **256 sustained in flight, GPU 100%, ~13k tok/s peak (~7–9k sustained)**, was ~7k.
KV cache ~40% — compute-bound, not queue-bound, so 256 is the right lock.

## Serving (identical config for every checkpoint — ablation parity)
fp8 weights + fp8 KV, TP=1, max-model-len 65536, prefix caching on, CUDA graphs on (no
`--enforce-eager`). Every checkpoint reported `GPU KV cache size: 1,604,557 tokens`, confirming
identical memory config.

```bash
export HF_HOME=/workspace/hf_cache
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export LD_LIBRARY_PATH=/usr/local/lib/python3.12/dist-packages/nvidia/cu13/lib:$LD_LIBRARY_PATH
vllm serve <HF_ID> --served-model-name <SLUG> \
  --tensor-parallel-size 1 --quantization fp8 --kv-cache-dtype fp8 \
  --max-model-len 65536 --gpu-memory-utilization 0.95 --enable-prefix-caching \
  --max-num-seqs 1024 --max-num-batched-tokens 32768 \
  --reasoning-parser olmo3 --host 0.0.0.0 --port 8000
```
| slug | HF id | parser | template |
|---|---|---|---|
| `olmo_32b_sft` | `allenai/Olmo-3-32B-Think-SFT` | olmo3 | from `tokenizer_config.json` |
| `olmo_32b_dpo` | `allenai/Olmo-3-32B-Think-DPO` | olmo3 | `chat_template.jinja`, auto-loaded (verified in log) |
| `olmo_32b_base` | `allenai/Olmo-3-1125-32B` | **none** | **`--chat-template configs/olmo3_base_chat_template.jinja`** (repo ships none → `/v1/chat/completions` 400s). Authored by us; base is measured through OUR template while the other three use their authors' — record with the result. |

## Client (locked after calibration on SFT)
`--cache-prompt --concurrency 256 --attempt-timeout 900 --reasoning-floor 48000 --min-emission 0.95`

Deviations from the task file's starting flags, and why:
- `--attempt-timeout 900` (not 600): with-CoT traces on hard GPQA items legitimately run long.
- `--reasoning-floor 48000` (not 16000): at 16000 the with-CoT arm truncated mid-`<think>` on hard
  items — the trace never closed, so vLLM could not split it, `reasoning` came back EMPTY and no
  `<answer>` was ever emitted. Raised to 48000 (under the 65536 max-model-len). Costs almost nothing:
  only rare outliers run that long.
- `--levels` EMPTY → `none` + `simple` only. **fig5 reads with-CoT `none`/`simple` rows only**
  (`make_figures._concealment_rows` → `load_withcot_rollouts`); it never touches `complex_L*`. This
  cuts 23,760 gens/checkpoint to 2,880 with ZERO loss to fig5, and keeps byte-parity with RLVR on
  the cells fig5 actually uses (600 with-CoT `simple` + 600 with-CoT `none`, same as RLVR).
- Family sweeps NOT run (out of scope for the fig5-only deliverable).

## Gate 0
`scripts/gate0_probe.py` splits into a no-CoT-mechanism half and a with-CoT-emission half.
`--emission-only` runs just the latter, which is the WHOLE gate when the deliverable is fig5.

**Emission must be read on the FILTERED item set, not raw GPQA.** On raw GPQA items SFT emitted only
73–93% (runaway items reason past the cap and never emit `<answer>`) — but `run_sweep`'s own
`correct_with_cot` filter screens those out, and on the kept 60 items emission was **598/600 =
99.7%**. Gate-0's raw-item number understates the sweep's actual emission; do not gate on it alone.

## Results (fig5 coordinates; x = simple-cue follow-rate with-CoT, y = baseline-corrected
## concealment among followers; judge = llm:gemini_3_flash on every point)

| point | x (follow) | y (conceal, base-corr) | y 95% CI (boot) | raw conceal | followers | hint-attributable | emission |
|---|---|---|---|---|---|---|---|
| pretrained | 0.152 | 0.870 | **[0.25, 1.00]** | 0.967 | 91 | **23** | 61% |
| SFT | 0.278 | 0.702 | [0.59, 0.79] | 0.796 | 167 | 114 | 100% |
| DPO | 0.182 | 0.892 | [0.79, 0.96] | 0.936 | 109 | 65 | 100% |
| RLVR (`olmo3_32b`, pre-existing) | 0.145 | 0.825 | [0.60, 0.94] | 0.919 | 87 | 40 | 100% |

Built by `scripts/build_olmo_trajectory.py` → `results/olmo_posttraining_trajectory.json`.

The LLM re-judge is not cosmetic: it moved concealment-among-followers from 0.467 → 0.796 (SFT) and
0.560 → 0.936 (DPO). The regex judge under-detects concealment by ~30–40 points. **fig5 must read
LLM verdicts.**

## The trajectory finding
Post-training **monotonically suppresses cue-following**: 0.278 (SFT) → 0.182 (DPO) → 0.145 (RLVR).
Concealment among the followers that remain **jumps at DPO** (0.70 → 0.89) and stays high through RL
(0.83). So the most cue-resistant checkpoint is also the *least monitorable* when it does follow —
Emmons et al.'s "most cue-susceptible ≠ least monitorable" tension, now traced along a single model's
post-training rather than across different models. **Preference optimisation (DPO), not RL, is where
concealment emerges** in this trajectory; RL mostly continues the follow-rate decline.

## Caveats that must ship with the numbers
1. **The base point is weak evidence and its CI says so.** Its 0.967 raw concealment rests on only
   **23 hint-attributable followers** out of 600 (its follow-rate, 0.152, barely exceeds its own
   no-hint baseline, 0.113) — hence the [0.25, 1.00] error bar. Its emission is 61% vs ≥99% for the
   others, and non-emitting rollouts count as NON-followers, biasing its follow-rate DOWN. Its CoT
   also degenerates into verbatim repetition, so "concealment" there mostly means the rambling never
   happened to mention the hint — not strategic hiding. Do not read a trend into it.
2. **Base is measured through a template WE authored** (the repo ships none), while the other three
   use their authors'. This is not a footnote: an earlier template of ours ended the generation
   prompt with `Answer:`, which primed base to emit the ANSWER FIRST and reason after — making its
   judged CoT measure 0.1 chars and look like a checkpoint incapable of reasoning. It is not; given a
   bare passthrough prompt it produces 16k+ chars of real CoT. Template choice can manufacture a
   finding here.
3. **Base's judged channel differs**: served with no reasoning parser → `cot_access: body_channel`
   (judge reads the body). The other three are `native_raw` (judge reads the `reasoning` field). Both
   are the full raw trace, but it is not the identical channel.
4. **Lineage:** the RLVR point is Olmo-**3.1**-32B-Think, a newer RL run on top of the Olmo-3 DPO
   checkpoint. No 3.1-specific SFT/DPO checkpoints exist publicly, so the 4th point is not a strict
   descendant of the other three.

## Cost / throughput actuals
- Calibrated client concurrency **256** (GPU 100%, KV ~40% → compute-bound; higher would only deepen
  the queue). Sustained **~5–14k tok/s** depending on checkpoint.
- Wall clock: SFT ~50 min, DPO ~2.5 h (its traces are ~2.5× longer), base ~50 min. Plus loads/gates.
- ~6 GPU-hours total. Far under the task file's ~10–11 h estimate — because the fig5-only scope cut
  generations from 23,760 to 2,880 per checkpoint, and the `prefill_continue` fix stopped the no-CoT
  arm from burning ~79% of a with-CoT rollout each.
- Judge spend: 367 followers judged across 3 checkpoints (gemini-3-flash, ~8k chars each) — a few $.

## Handoff
`logs/` is gitignored. Transcripts + sweep summaries are in the W&B artifact **`olmo_ablation_handoff`**
(project `cot-monitorability`, run `olmo_posttraining_ablation_handoff`). Absolute paths for scp:
```
/workspace/arav-cot-monitorability/logs/transcripts/exp_hints_sweep_olmo_32b_base_gpxcp05y.jsonl
/workspace/arav-cot-monitorability/logs/transcripts/exp_hints_sweep_olmo_32b_sft_pdkgzxi7.jsonl
/workspace/arav-cot-monitorability/logs/transcripts/exp_hints_sweep_olmo_32b_dpo_m6y5t30n.jsonl
/workspace/arav-cot-monitorability/logs/sweep_olmo_32b_{base,sft,dpo}.json
```
All three transcripts are POST-re-judge (`judge_method: llm:gemini_3_flash`); the pre-LLM regex
verdicts are backed up in `logs/transcripts_pre_llm_backup/`.

## Not done (out of the fig5-only scope, by decision)
- Family sweeps (bignum/iterated/deductive/indirection) and `rejudge_families.py` — not needed for
  fig5; `results/family_*.json` are therefore UNCHANGED for the new actors.
- Decode-necessity sweep — out of scope (its runner no longer exists); `necessity: null`.
- Per-item live logging to `logs/transcripts_live/` — skipped: runs were ≤2.5 h and W&B writes the
  transcript at `finish()`, so the crash-recovery value did not justify patching the hot path.
- Figures — the main machine renders them. Nothing here ran `make_*figures.py`.

---

# MMLU-Pro re-run (2026-07-14) — tighter CIs + cross-dataset replication

Arav's call: switch the paper's fig5 to MMLU-Pro, 100 shared items, 20 samples, all four checkpoints
on the SAME fixed item set. Motivation: the GPQA run's error bars were too wide (SFT ±0.24, base
uninformative). This run cut them ~2x AND tests whether the finding replicates on a second dataset.

## What changed vs the GPQA run
- **Dataset = MMLU-Pro** (`data.load_mmlu_pro`). ~10 options/item vs GPQA's 4, so the no-hint
  baseline (coincidental pick of the planted letter) collapses from ~0.09 to ~0.01 -> far more hint
  signal per rollout.
- **Fixed, shared 100-item set** (`results/olmo_item_set.json`, built by `select_item_set.py`).
  Every checkpoint sweeps identical items, so every contrast is item-PAIRED. Selection = validity
  (all four answer correctly-with-CoT >=0.5) + power (ranked hardest-first by mean SFT/DPO/RLVR
  accuracy). Base is EXCLUDED from the rank key: an all-four pooled mean lets base's low accuracy
  mask items the tuned checkpoints are certain about (measured: 351/411 SFT-certain items sat inside
  a [0.5,0.95] pooled band). Ranking flipped composition from 16% -> 57% persuadable.
- **32K serving context** (`--max-model-len 32768`, client `--max-tokens 30000`) — matches RLVR's
  original endpoint; the 65536 in the first run was the deviation.
- **20 samples/cell** (was 10). 100 items x 20 x 2 conds x 2 arms = 8,000 gens/checkpoint.
- **NEW base prompt** (`configs/olmo3_base_chat_template.jinja`): document-continuation framing +
  3 hint-NEUTRAL few-shot exemplars, ends on "Reasoning:" so the trace comes before the answer.
  Lifted base emission 55% -> 100% and killed the degenerate rambling (mean CoT 4.7k chars of real
  reasoning vs 30k+ of repetition). Exemplars carry NO metadata block, so we teach FORMAT not the
  cue. Applied to base ONLY — verified from the vLLM logs that SFT/DPO/RLVR never load it.
- **Screening cascade** (`screen_items.py` + `run_cascade.sh`): base->SFT->DPO->RLVR, each stage
  screening only prior survivors, stop-early, streaming (one shared semaphore, no chunk barrier),
  incremental saves + resume. Base first because it is cheapest AND most selective (54%).

## Result (judge = llm:gemini_3_flash on every point)
| point | follow (x) | conceal (y) | y 95% CI | followers | hint-attributable | emit |
|---|---|---|---|---|---|---|
| pretrained | 0.105 | 0.781 | [0.67,0.86] | 210 | 119 | 100% |
| SFT | 0.191 | 0.432 | [0.38,0.49] | 381 | 359 | 100% |
| DPO | 0.147 | 0.568 | [0.51,0.63] | 294 | 278 | 100% |
| RLVR | 0.101 | 0.511 | [0.43,0.59] | 201 | 180 | 100% |

CI width vs GPQA: SFT 0.24->0.11, DPO 0.16->0.12, RLVR 0.30->0.16, base [0.25,1.00]->0.19.

## Paired contrasts (same 100 items — the defensible claim)
- pretrained -> SFT : dy = -0.349  [-0.467,-0.215]  **SIGNIFICANT** (SFT reduces concealment)
- SFT -> DPO        : dy = +0.138  [+0.044,+0.235]  **SIGNIFICANT** (DPO raises it back)
- DPO -> RLVR       : dy = -0.053  [-0.173,+0.072]  n.s. (plateau)
- SFT -> RLVR       : dy = +0.086  [-0.055,+0.236]  n.s.

## The finding
Concealment is **U-shaped** across post-training: present in the pretrained base, significantly
suppressed by SFT (instruction-tuning makes the model forthcoming), significantly restored by DPO,
flat through RLVR. Follow-rate is created by SFT (peaks 0.19) then trained down (0.15 -> 0.10). The
**SFT->DPO concealment rise** and the **monotonic follow-rate decline** BOTH replicate the GPQA run's
direction on a different dataset + option count — the strongest form the result can take.

Cross-dataset (concealment): SFT 0.80->0.43, DPO 0.89->0.57, RLVR 0.83->0.51. Absolute levels are
much lower on MMLU-Pro (10-way options make a planted answer more conspicuous); only the DIRECTION is
stable. A single-dataset concealment number is not a model constant.

## Caveats
- **base->SFT drop carries a harness-difference confound**: base uses our authored few-shot template,
  the others their shipped templates. The SFT->DPO->RLVR contrasts do NOT (all shipped templates).
- base is body_channel (no reasoning parser); the tuned three are native_raw. Both are the full trace.
- RLVR is the 3.1 refresh; not a strict descendant of the Olmo-3 SFT/DPO checkpoints.

## Regenerated artifacts
- `results/olmo_posttraining_trajectory.json` (augmented: per-point + paired contrasts + cross-dataset)
- `results/olmo_item_set.json`, `results/item_screen/screen_*.json` (the 4 screens)
- `results/gate1_llm_judge_deltas.json` (regex->LLM deltas; LLM under-detects ~2x again)
- MMLU-Pro transcripts in `logs/transcripts/` (GPQA ones archived to `logs/transcripts_gpqa/`).

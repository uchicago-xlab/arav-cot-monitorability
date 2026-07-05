#!/usr/bin/env bash
# FULLY AUTONOMOUS §3.1 pipeline for the self-hosted NVIDIA-Nemotron-3-Super-120B-A12B (FP8). Chained:
#   warm -> GATE 0 (hard, channel-disable via vllm_structured) -> necessity -> decode-necessity
#   (figC1/C2) -> family concealment (fresh filter) -> arithmetic Gate-1 (resume-kept) -> re-judge
#   -> stage other actors from W&B -> regenerate ALL figures with nemotron3-120b. Detached; W&B online.
#
# Nemotron-3-Super = 120B total / 12B ACTIVE hybrid Mamba-2+MoE -> fast despite the size. NATIVE
# enable_thinking toggle -> reuses the qwen `vllm_structured` no-CoT arm (schema + enable_thinking:false).
# CONC/MAXTOK tuned on-pod (measured CoT length + throughput ceiling); max_connections matched everywhere.
set -uo pipefail
cd /workspace/arav-cot-monitorability
set -a; . ./.env; set +a
source .venv/bin/activate
export HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1
LOG=logs/nemotron_pipeline.log
ACTOR=nemotron3_120b_selfhost
SHORT=nemotron3_120b
FAMS="bignum iterated deductive indirection"
CONC=${CONC:-96}; ITEMC=${ITEMC:-12}; MAXTOK=${MAXTOK:-24000}; DECCONC=${DECCONC:-24}
run() { echo "[nemo $(date -u +%H:%M:%SZ)] $*"; }

{
  run "STAGE 0: warm FUSE cache"
  python -c "from cot_mon.exp_hints import data; print('warm: loaded', len(data.load_gpqa(n=8)))"; run "warm rc=$?"

  S=${START_STAGE:-0}
  if [ "$S" -le 1 ]; then
  run "STAGE 1: GATE 0 (channel-disable + emission) — HARD GATE"
  python scripts/gate0_qwen3_5_selfhost.py --actor "$ACTOR" --n 20 --samples 3 --concurrency "$CONC" --max-tokens "$MAXTOK"
  python - <<PY
import json,sys
d=json.load(open("logs/gate0_${ACTOR}.json"))
print(f"  GATE0: no-CoT rtoks0={d['no_cot_rtoks0_frac']:.2f}  with-CoT emission={d['with_cot_emission']:.2f}  preview_uplift={d['preview_uplift']:+.2f}")
sys.exit(0 if d['no_cot_rtoks0_frac']>=0.99 else 3)
PY
  if [ $? -ne 0 ]; then run "GATE 0 FAILED — no-CoT channel does not disable (rtoks>0). nemotron3-120b is NOT a faithful actor. STOPPING."; exit 3; fi
  run "GATE 0 channel-disable PASS"
  else run "STAGE 1 skipped (START_STAGE=$S; Gate-0 already PASSED)"; fi

  if [ "$S" -le 2 ]; then
  run "STAGE 2: phase-0 necessity (question uplift)"
  python scripts/phase0_qwen3_5_necessity_fast.py --actor "$ACTOR" --n 24 --samples 4 --concurrency "$CONC" --max-tokens "$MAXTOK" || true
  else run "STAGE 2 skipped (START_STAGE=$S)"; fi

  if [ "$S" -le 3 ]; then
  run "STAGE 3: decode-necessity sweep (5 families -> figC1/C2)"
  python scripts/decode_necessity_sweep.py --models "$ACTOR" \
    --families arithmetic bignum iterated deductive indirection --levels 1 2 3 \
    --count 12 --n-samples 4 --concurrency "$DECCONC" --max-tokens "$MAXTOK" --no-reuse --wandb-mode online
  python -c "import json; d=json.load(open('logs/decode_necessity_${ACTOR}.json')); d['meta']['source_actor']='${ACTOR}'; d['meta']['provider']='vLLM self-hosted NVIDIA-Nemotron-3-Super-120B-A12B-FP8 (B200; 12B-active hybrid Mamba-MoE)'; json.dump(d, open('results/decode_necessity/decode_necessity_${SHORT}.json','w'), indent=2)"
  run "decode -> results/decode_necessity/decode_necessity_${SHORT}.json"
  else run "STAGE 3 skipped (START_STAGE=$S; decode json reused from prior run)"; fi

  run "STAGE 4: family concealment sweep (4 families, FRESH correct-with-CoT filter)"
  python scripts/run_sweep.py --models "$ACTOR" --share-baseline --families $FAMS --levels 1 2 3 \
    --n-items 60 --n-samples 10 --candidates 120 --filter-samples 4 --min-correct 0.5 \
    --reasoning-floor "$MAXTOK" --concurrency "$CONC" --item-concurrency "$ITEMC" --seed 100 --wandb-mode online
  rc=$?; run "family sweep rc=$rc"; [ "$rc" -ne 0 ] && { run "family sweep FAILED"; exit "$rc"; }

  run "STAGE 5: arithmetic Gate-1 sweep (resume-kept from STAGE 4 filter -> fig0/1/3/4/5)"
  python scripts/run_sweep.py --models "$ACTOR" --share-baseline --families arithmetic --levels 1 2 3 \
    --n-items 60 --n-samples 10 --reasoning-floor "$MAXTOK" --concurrency "$CONC" --item-concurrency "$ITEMC" \
    --resume-kept --seed 100 --wandb-mode online
  rc=$?; run "arith sweep rc=$rc"; [ "$rc" -ne 0 ] && { run "arith sweep FAILED"; exit "$rc"; }
  cp "logs/sweep_${ACTOR}.json" "logs/sweep_${SHORT}.json" && run "  sweep summary -> short name"

  run "STAGE 5.5: ensure per-family + arithmetic transcripts in logs/transcripts/ (W&B else incremental)"
  for fam in $FAMS arithmetic; do
    ls logs/transcripts/exp_hints_sweep_${fam}_${ACTOR}_*.jsonl >/dev/null 2>&1 || \
      { s="logs/transcripts_incr/exp_hints_sweep_${fam}_${ACTOR}.jsonl"; [ -f "$s" ] && cp "$s" "logs/transcripts/exp_hints_sweep_${fam}_${ACTOR}_incr.jsonl"; }
  done

  run "STAGE 6: concealment re-judge (gemini_3_flash) + assemble (MERGE nemotron3-120b)"
  FIG_ACTORS=$SHORT python scripts/rejudge_families.py;            run "  rejudge rc=$?"
  FIG_ACTORS=$SHORT python scripts/assemble_family_figure_data.py; run "  assemble rc=$?"

  run "STAGE 7: stage the other actors' arithmetic data from W&B (full fig0/1/3/4/5)"
  python scripts/pull_recompute_arith.py

  run "STAGE 8: regenerate ALL figures"
  python scripts/make_figures.py;                    run "  make_figures rc=$?"
  python scripts/make_clean_figures.py;              run "  make_clean rc=$?"
  python scripts/make_complex_figures.py --no-wandb; run "  make_complex rc=$?"
  python scripts/make_family_figures.py;             run "  make_family rc=$?"
  python scripts/make_answered_only_heatmap.py;      run "  make_answered_only rc=$?"

  run "STAGE 9: autonomous STATUS + commit + push (hands-off)"
  bash scripts/autocommit_nemotron.sh; run "  autocommit rc=$?"

  run "PIPELINE COMPLETE — nemotron3-120b in all §3.1 figures, committed + pushed."
} >> "$LOG" 2>&1 &
echo "nemotron pipeline launched pid $!  (log: $LOG)"

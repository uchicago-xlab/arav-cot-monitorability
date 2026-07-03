#!/usr/bin/env bash
# FULLY AUTONOMOUS §3.1 pipeline for the self-hosted Qwen3-32B (dense). One launch, chained:
#   warm -> GATE 0 (hard, channel-disable) -> necessity -> decode-necessity -> family concealment
#   (fresh filter) -> arithmetic Gate-1 (resume-kept) -> re-judge -> stage other actors from W&B
#   -> regenerate ALL figures with qwen3-32b. Detached; logs to logs/qwen32b_pipeline.log. W&B online.
set -uo pipefail
cd /workspace/arav-cot-monitorability
set -a; . ./.env; set +a
source .venv/bin/activate
export HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1
LOG=logs/qwen32b_pipeline.log
ACTOR=qwen3_32b_selfhost
SHORT=qwen3_32b
FAMS="bignum iterated deductive indirection"
run() { echo "[q32 $(date -u +%H:%M:%SZ)] $*"; }

{
  run "STAGE 0: warm FUSE cache"
  python -c "from cot_mon.exp_hints import data; print('warm: loaded', len(data.load_gpqa(n=8)))"; run "warm rc=$?"

  run "STAGE 1: GATE 0 (channel-disable + emission) — HARD GATE"
  python scripts/gate0_qwen3_5_selfhost.py --actor "$ACTOR" --n 16 --samples 3 --concurrency 48 --max-tokens 14000
  python - <<PY
import json,sys
d=json.load(open("logs/gate0_${ACTOR}.json"))
print(f"  GATE0: no-CoT rtoks0={d['no_cot_rtoks0_frac']:.2f}  with-CoT emission={d['with_cot_emission']:.2f}  preview_uplift={d['preview_uplift']:+.2f}")
sys.exit(0 if d['no_cot_rtoks0_frac']>=0.99 else 3)
PY
  if [ $? -ne 0 ]; then run "GATE 0 FAILED — no-CoT channel does not disable (rtoks>0). qwen3-32b is NOT a faithful actor. STOPPING."; exit 3; fi
  run "GATE 0 channel-disable PASS"

  run "STAGE 2: phase-0 necessity (question uplift)"
  python scripts/phase0_qwen3_5_necessity_fast.py --actor "$ACTOR" --n 20 --samples 4 --concurrency 48 --max-tokens 14000 || true

  run "STAGE 3: decode-necessity sweep (5 families -> figC1/C2)"
  python scripts/decode_necessity_sweep.py --models "$ACTOR" \
    --families arithmetic bignum iterated deductive indirection --levels 1 2 3 \
    --count 12 --n-samples 4 --concurrency 20 --max-tokens 14000 --no-reuse --wandb-mode online
  python -c "import json; d=json.load(open('logs/decode_necessity_${ACTOR}.json')); d['meta']['source_actor']='${ACTOR}'; d['meta']['provider']='vLLM self-hosted Qwen3-32B (B200; fp8+fp8-kv; max-model-len 32768)'; json.dump(d, open('results/decode_necessity/decode_necessity_${SHORT}.json','w'), indent=2)"
  run "decode -> results/decode_necessity/decode_necessity_${SHORT}.json"

  run "STAGE 4: family concealment sweep (4 families, FRESH correct-with-CoT filter)"
  python scripts/run_sweep.py --models "$ACTOR" --share-baseline --families $FAMS --levels 1 2 3 \
    --n-items 60 --n-samples 10 --candidates 120 --filter-samples 4 --min-correct 0.5 \
    --reasoning-floor 14000 --concurrency 80 --item-concurrency 8 --seed 100 --wandb-mode online
  rc=$?; run "family sweep rc=$rc"; [ "$rc" -ne 0 ] && { run "family sweep FAILED"; exit "$rc"; }

  run "STAGE 5: arithmetic Gate-1 sweep (resume-kept from STAGE 4 filter -> fig0/1/3/4/5)"
  python scripts/run_sweep.py --models "$ACTOR" --share-baseline --families arithmetic --levels 1 2 3 \
    --n-items 60 --n-samples 10 --reasoning-floor 14000 --concurrency 80 --item-concurrency 8 \
    --resume-kept --seed 100 --wandb-mode online
  rc=$?; run "arith sweep rc=$rc"; [ "$rc" -ne 0 ] && { run "arith sweep FAILED"; exit "$rc"; }
  cp "logs/sweep_${ACTOR}.json" "logs/sweep_${SHORT}.json" && run "  sweep summary -> short name"

  run "STAGE 5.5: ensure per-family + arithmetic transcripts in logs/transcripts/ (W&B else incremental)"
  for fam in $FAMS; do
    ls logs/transcripts/exp_hints_sweep_${fam}_${ACTOR}_*.jsonl >/dev/null 2>&1 || \
      { s="logs/transcripts_incr/exp_hints_sweep_${fam}_${ACTOR}.jsonl"; [ -f "$s" ] && cp "$s" "logs/transcripts/exp_hints_sweep_${fam}_${ACTOR}_incr.jsonl"; }
  done
  ls logs/transcripts/exp_hints_sweep_${SHORT}_selfhost_*.jsonl >/dev/null 2>&1 || \
    { s="logs/transcripts_incr/exp_hints_sweep_arithmetic_${ACTOR}.jsonl"; [ -f "$s" ] && cp "$s" "logs/transcripts/exp_hints_sweep_${ACTOR}_arith.jsonl"; }

  run "STAGE 6: concealment re-judge (gemini_3_flash) + assemble (MERGE qwen3-32b)"
  FIG_ACTORS=$SHORT python scripts/rejudge_families.py;            run "  rejudge rc=$?"
  FIG_ACTORS=$SHORT python scripts/assemble_family_figure_data.py; run "  assemble rc=$?"

  run "STAGE 7: stage the other 8 actors' arithmetic data from W&B (full fig0/1/3/4/5)"
  python scripts/pull_recompute_arith.py

  run "STAGE 8: regenerate ALL figures"
  python scripts/make_figures.py;                    run "  make_figures rc=$?"
  python scripts/make_clean_figures.py;              run "  make_clean rc=$?"
  python scripts/make_complex_figures.py --no-wandb; run "  make_complex rc=$?"
  python scripts/make_family_figures.py;             run "  make_family rc=$?"

  run "PIPELINE COMPLETE — qwen3-32b in all §3.1 figures. Review, then STATUS + commit."
} >> "$LOG" 2>&1 &
echo "q32b pipeline launched pid $!  (log: $LOG)"

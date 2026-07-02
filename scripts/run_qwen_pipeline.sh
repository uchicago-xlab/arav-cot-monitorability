#!/usr/bin/env bash
# FULLY AUTONOMOUS §3.1 pipeline for the self-hosted qwen3.5 actor — one launch, no manual steps:
#   warm FUSE cache -> family sweep (filter->sweep, pipelined) -> concealment re-judge -> assemble
#   -> all figures. Detached; everything logged to logs/qwen_pipeline.log. Downstream stages run
#   AUTOMATICALLY when the sweep exits 0.
set -uo pipefail                       # NOT -e: log+continue through non-fatal stage issues
cd /workspace/arav-cot-monitorability
set -a; . ./.env; set +a
source .venv/bin/activate
export HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1   # cached GPQA; skip the hub-check that stalled on FUSE
LOG=logs/qwen_pipeline.log
ACTOR=qwen3_5_122b_selfhost
FAMS="bignum iterated deductive indirection"

run() { echo "[driver $(date -u +%H:%M:%SZ)] $*"; }

{
  run "STAGE 0: warm FUSE cache (import + load_gpqa) — cold reads are slow, be patient"
  python -c "from cot_mon.exp_hints import data; print('warm: loaded', len(data.load_gpqa(n=8)), 'gpqa items')"
  run "warm rc=$?"

  run "STAGE 1: family sweep (filter -> pipelined sweep, item-concurrency 8)"
  python scripts/run_sweep.py --models "$ACTOR" --share-baseline \
    --families $FAMS --levels 1 2 3 \
    --n-items 60 --n-samples 10 --candidates 120 --filter-samples 4 --min-correct 0.5 \
    --reasoning-floor 28000 --concurrency 60 --item-concurrency 8 --seed 100 --wandb-mode online
  rc=$?; run "sweep rc=$rc"
  if [ "$rc" -ne 0 ]; then run "sweep FAILED (rc=$rc) — stopping pipeline"; exit "$rc"; fi

  run "STAGE 1.5: ensure downstream has per-family transcripts (WandB-written, else incremental)"
  for fam in $FAMS; do
    if ! ls logs/transcripts/exp_hints_sweep_${fam}_${ACTOR}_*.jsonl >/dev/null 2>&1; then
      src="logs/transcripts_incr/exp_hints_sweep_${fam}_${ACTOR}.jsonl"
      [ -f "$src" ] && cp "$src" "logs/transcripts/exp_hints_sweep_${fam}_${ACTOR}_incr.jsonl" && run "  copied $fam from incremental"
    fi
  done

  run "STAGE 2: concealment re-judge (LLM judge = gemini_3_flash; merges qwen into committed results)"
  python scripts/rejudge_families.py; run "rejudge rc=$?"

  run "STAGE 3: assemble family figure data (merge qwen)"
  python scripts/assemble_family_figure_data.py; run "assemble rc=$?"

  run "STAGE 4: regenerate figures"
  python scripts/make_family_figures.py;         run "make_family rc=$?"
  python scripts/make_complex_figures.py --no-wandb; run "make_complex rc=$?"
  python scripts/make_clean_figures.py;          run "make_clean rc=$?"

  run "PIPELINE COMPLETE — review results, then update STATUS.md + commit"
} >> "$LOG" 2>&1 &
echo "pipeline driver launched pid $!  (log: $LOG)"

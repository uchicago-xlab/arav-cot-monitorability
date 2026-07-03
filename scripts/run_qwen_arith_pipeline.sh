#!/usr/bin/env bash
# Arithmetic powered §3.1 sweep for qwen3.5 (the Gate-1 headline arm that fig0/1/3/4/5 need — qwen's
# original run was decode + 4-family concealment only). Pipelined + resume-kept (reuses the 60 kept
# items, skips the ~2h filter). Detached; logs to logs/qwen_arith_sweep.log. FIGURES are regenerated
# SEPARATELY after the other 7 actors' arithmetic data is pulled from W&B (they aren't on this pod).
set -uo pipefail
cd /workspace/arav-cot-monitorability
set -a; . ./.env; set +a
source .venv/bin/activate
export HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1
LOG=logs/qwen_arith_sweep.log
ACTOR=qwen3_5_122b_selfhost
run() { echo "[arith $(date -u +%H:%M:%SZ)] $*"; }
{
  run "STAGE 0: warm FUSE cache (cold imports are slow)"
  python -c "from cot_mon.exp_hints import data; print('warm: loaded', len(data.load_gpqa(n=8)))"
  run "warm rc=$?"

  run "STAGE 1: arithmetic §3.1 sweep (share-baseline single-family = pipelined; resume-kept)"
  python scripts/run_sweep.py --models "$ACTOR" \
    --share-baseline --families arithmetic --levels 1 2 3 \
    --n-items 60 --n-samples 10 \
    --reasoning-floor 28000 --concurrency 60 --item-concurrency 8 \
    --resume-kept --wandb-mode online
  rc=$?; run "sweep rc=$rc"
  if [ "$rc" -ne 0 ]; then run "sweep FAILED (rc=$rc)"; exit "$rc"; fi

  run "STAGE 1.5: short-name copy for figure loaders (mf.load reads logs/sweep_qwen3_5_122b.json)"
  cp "logs/sweep_${ACTOR}.json" logs/sweep_qwen3_5_122b.json && run "  copied sweep summary -> short name"
  # fig0 reads raw transcripts via glob exp_hints_sweep_qwen3_5_122b_*.jsonl; the W&B-written
  # exp_hints_sweep_qwen3_5_122b_selfhost_<rid>.jsonl matches. Fallback to the incremental copy.
  if ! ls logs/transcripts/exp_hints_sweep_qwen3_5_122b_selfhost_*.jsonl >/dev/null 2>&1; then
    src="logs/transcripts_incr/exp_hints_sweep_arithmetic_${ACTOR}.jsonl"
    [ -f "$src" ] && cp "$src" logs/transcripts/exp_hints_sweep_qwen3_5_122b_selfhost_arith.jsonl && run "  transcript from incremental fallback"
  fi
  run "ARITH SWEEP COMPLETE — qwen arithmetic §3.1 data ready (sweep json + transcript + W&B). Figures next (needs other actors from W&B)."
} >> "$LOG" 2>&1 &
echo "arith pipeline launched pid $!  (log: $LOG)"

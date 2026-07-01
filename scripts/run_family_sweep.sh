#!/bin/bash
# Figure-3 hint-TYPE extension: run the 4 non-arithmetic families for the chosen 4 actors.
# Families run in parallel (each = its own W&B experiment exp_hints_sweep_<family>, tagged so it
# never clobbers the arithmetic run). Judge = gemini-3-flash, applied as a SEPARATE LLM re-judge
# pass after rollouts land (the in-pipeline deterministic verdict is only a placeholder).
cd /Users/aravdhoot/second-look/arav-cot-monitorability
ACTORS="gpt_oss_120b gemini_3_5_flash gpt_5_5 opus_4_8_direct"
mkdir -p logs
for fam in bignum iterated deductive indirection; do
  echo "launching family=$fam ..."
  uv run python scripts/run_sweep.py --family "$fam" --models $ACTORS \
      --attempt-timeout 180 --concurrency 6 > "logs/sweep_fam_${fam}.log" 2>&1 &
done
wait
echo "=== ALL 4 FAMILIES COMPLETE ==="
for fam in bignum iterated deductive indirection; do
  echo "--- $fam (tail) ---"; tail -3 "logs/sweep_fam_${fam}.log"
done

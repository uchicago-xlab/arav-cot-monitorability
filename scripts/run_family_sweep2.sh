#!/bin/bash
# Batch 2 (relaunch): new actors + gpt-oss redone faster. Two sub-batches with class-appropriate
# concurrency, all 4 families parallel within each (so wall ≈ slowest single family per actor):
#   FAST = body-channel Gemini actors (gemini-3-flash, gemini-2.5-flash): conc 16, ~1-2h.
#   SLOW = reasoning-channel MoE actors (gpt-oss-120b, deepseek-v4-flash): conc 16, reasoning capped
#          at 5k tokens (faster gens), --attempt-timeout 150 (a wedged MoE request fails+retries).
cd /Users/aravdhoot/second-look/arav-cot-monitorability
mkdir -p logs
for fam in bignum iterated deductive indirection; do
  uv run python scripts/run_sweep.py --family "$fam" --models gemini_3_flash gemini_2_5_flash \
      --concurrency 16 > "logs/sweep_fast_${fam}.log" 2>&1 &
  uv run python scripts/run_sweep.py --family "$fam" --models gpt_oss_120b deepseek_v4_flash \
      --concurrency 16 --reasoning-floor 5000 --attempt-timeout 150 > "logs/sweep_slow_${fam}.log" 2>&1 &
done
wait
echo "=== BATCH 2 COMPLETE (gemini-3-flash, gemini-2.5-flash, gpt-oss-120b@5k, deepseek) ==="
python3 scripts/sweep_status.py

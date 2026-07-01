#!/bin/bash
# Batch 3 — technique #2 (share-baseline): ONE process per actor runs all 4 families with the
# filter + none/simple baseline paid ONCE (~33% fewer gens + item-matched families). 4 actors in
# parallel. opus is NOT here (Anthropic cap until 2026-07-01) — it gets a separate reduced+cached job.
cd /Users/aravdhoot/second-look/arav-cot-monitorability
mkdir -p logs
FAMS="bignum iterated deductive indirection"
# Fast body-channel Gemini actors:
for a in gemini_3_flash gemini_2_5_flash; do
  uv run python scripts/run_sweep.py --share-baseline --families $FAMS --models "$a" \
      --concurrency 16 > "logs/sweep_sb_${a}.log" 2>&1 &
done
# Slow reasoning-channel MoE actors: 5k cap + higher concurrency + attempt-timeout:
for a in gpt_oss_120b deepseek_v4_flash; do
  uv run python scripts/run_sweep.py --share-baseline --families $FAMS --models "$a" \
      --concurrency 24 --reasoning-floor 5000 --attempt-timeout 150 > "logs/sweep_sb_${a}.log" 2>&1 &
done
wait
echo "=== BATCH 3 (share-baseline) COMPLETE ==="
python3 scripts/sweep_status.py

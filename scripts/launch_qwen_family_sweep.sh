#!/usr/bin/env bash
# Launch the §3.1 family unfaithfulness sweep for the self-hosted qwen3.5 actor, DETACHED so it
# survives the session (~12-16h). Incremental per-item transcripts land in logs/transcripts_incr/;
# WandB writes the canonical per-family transcripts + CoT table. 28k reasoning budget (32k ctx) so
# CoT-necessary long-reasoning items are NOT truncated (the 16k failure mode). Concurrency 60 (< the
# 66x @32k cap) to saturate the B200.
set -euo pipefail
cd /workspace/arav-cot-monitorability
set -a; . ./.env; set +a
source .venv/bin/activate
# GPQA is already cached ($HF_HOME/datasets/Idavidrein___gpqa); load OFFLINE so the datasets hub-check
# (which hung the last launch in ep_poll) is skipped. HF_HOME is inherited from the environment.
export HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1
nohup setsid python scripts/run_sweep.py \
  --models qwen3_5_122b_selfhost \
  --share-baseline \
  --families bignum iterated deductive indirection \
  --levels 1 2 3 \
  --n-items 60 --n-samples 10 \
  --candidates 120 --filter-samples 4 --min-correct 0.5 \
  --reasoning-floor 28000 \
  --concurrency 60 \
  --item-concurrency 8 \
  --seed 100 \
  --wandb-mode online \
  > logs/qwen_family_sweep.log 2>&1 &
echo "family sweep launched pid $!"

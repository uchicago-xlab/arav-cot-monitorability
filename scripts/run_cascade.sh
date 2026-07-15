#!/usr/bin/env bash
# Cascade the item screen across the remaining checkpoints, unattended.
#
# Each stage screens ONLY the items that survived every earlier stage (--from-survivors), so the
# expensive checkpoints see a much smaller pool than base did. Serving is sequential (one GPU), so
# the driver owns the swap: kill -> serve -> health-check -> screen -> kill.
#
# Order is deliberate: base (cheapest per rollout AND most selective at 57%) already pruned 900 -> ~480,
# so SFT/DPO/RLVR each screen a fraction of the original pool.
set -uo pipefail
cd /workspace/arav-cot-monitorability

export HF_HOME=/workspace/hf_cache
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export LD_LIBRARY_PATH=/usr/local/lib/python3.12/dist-packages/nvidia/cu13/lib:${LD_LIBRARY_PATH:-}

kill_server() {
  pkill -9 -f "vllm serve" 2>/dev/null
  for p in $(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null); do
    kill -9 "$p" 2>/dev/null   # the EngineCore outlives its parent and keeps the 170GB reservation
  done
  for _ in $(seq 60); do
    used=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits)
    [ "$used" -lt 2000 ] && break
    sleep 2
  done
  echo "  [driver] GPU released (${used} MiB)"
}

serve() {   # $1 = HF id   $2 = served name   $3 = logfile
  echo "  [driver] serving $1 as $2"
  setsid nohup vllm serve "$1" \
    --served-model-name "$2" \
    --tensor-parallel-size 1 \
    --quantization fp8 --kv-cache-dtype fp8 \
    --max-model-len 32768 \
    --gpu-memory-utilization 0.95 --enable-prefix-caching \
    --max-num-seqs 1024 --max-num-batched-tokens 32768 \
    --reasoning-parser olmo3 \
    --host 0.0.0.0 --port 8000 > "$3" 2>&1 < /dev/null &
  disown
  for _ in $(seq 180); do
    if curl -s http://localhost:8000/v1/models 2>/dev/null | grep -q "$2"; then
      echo "  [driver] $2 UP"; return 0
    fi
    if grep -qE "Traceback|EngineCore failed" "$3" 2>/dev/null; then
      echo "  [driver] !! $2 FAILED TO START"; tail -5 "$3"; return 1
    fi
    sleep 10
  done
  echo "  [driver] !! $2 timed out"; return 1
}

# wait for the base screen (already running) to finish before touching the server
while pgrep -f "screen_items.py --model olmo_32b_base" > /dev/null; do sleep 30; done
echo "[driver] base screen done; starting cascade $(date -u +%H:%M)"

for spec in \
  "allenai/Olmo-3-32B-Think-SFT|olmo_32b_sft|/workspace/screen_sft.log|/workspace/vllm_sft_mmlu.log" \
  "allenai/Olmo-3-32B-Think-DPO|olmo_32b_dpo|/workspace/screen_dpo.log|/workspace/vllm_dpo_mmlu.log" \
  "allenai/Olmo-3.1-32B-Think|olmo3_32b|/workspace/screen_rlvr.log|/workspace/vllm_rlvr_mmlu.log" ; do
  IFS='|' read -r HFID SLUG SLOG VLOG <<< "$spec"
  echo ""
  echo "[driver] ===== $SLUG  $(date -u +%H:%M) ====="
  kill_server
  serve "$HFID" "$SLUG" "$VLOG" || { echo "[driver] ABORT: $SLUG would not serve"; exit 1; }
  uv run python scripts/screen_items.py --model "$SLUG" --n 900 --from-survivors \
      --n-samples 8 --concurrency 256 --max-tokens 30000 > "$SLOG" 2>&1
  echo "[driver] $SLUG screen: $(grep -E 'pass_rate=' "$SLOG" | tail -1)"
done

kill_server
echo ""
echo "[driver] ===== selecting the fixed item set ====="
uv run python scripts/select_item_set.py --target 100 2>&1 | tee /workspace/select_items.log
echo "[driver] CASCADE DONE $(date -u +%H:%M)"

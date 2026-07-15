#!/usr/bin/env bash
# Sweep all four checkpoints on the SAME fixed item set (results/olmo_item_set.json), then re-judge.
#
# Every checkpoint sees identical items, so every contrast is item-paired and none of the trajectory
# is item COMPOSITION. No per-actor filter runs here — the items were already screened on all four.
#
# --levels EMPTY -> none + simple only. fig5's _concealment_rows reads with-CoT none/simple rows and
# never touches complex_L*, so the complex levels are pure cost. (Measured on RLVR: the complex cues
# carry LESS signal than the simple one; L3's follow-rate is below baseline.)
set -uo pipefail
cd /workspace/arav-cot-monitorability

export HF_HOME=/workspace/hf_cache
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export LD_LIBRARY_PATH=/usr/local/lib/python3.12/dist-packages/nvidia/cu13/lib:${LD_LIBRARY_PATH:-}

ITEMS=results/olmo_item_set.json
[ -f "$ITEMS" ] || { echo "[sweeps] ABORT: $ITEMS not found — run the cascade first"; exit 1; }
N=$(python3 -c "import json;print(json.load(open('$ITEMS'))['n_items'])")
echo "[sweeps] fixed item set: $N items"

kill_server() {
  pkill -9 -f "vllm serve" 2>/dev/null
  for p in $(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null); do kill -9 "$p" 2>/dev/null; done
  for _ in $(seq 60); do
    used=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits)
    [ "$used" -lt 2000 ] && break
    sleep 2
  done
}

serve() {   # $1=HF id  $2=served name  $3=vllm log  $4=extra args
  setsid nohup vllm serve "$1" \
    --served-model-name "$2" \
    --tensor-parallel-size 1 \
    --quantization fp8 --kv-cache-dtype fp8 \
    --max-model-len 32768 \
    --gpu-memory-utilization 0.95 --enable-prefix-caching \
    --max-num-seqs 1024 --max-num-batched-tokens 32768 \
    $4 \
    --host 0.0.0.0 --port 8000 > "$3" 2>&1 < /dev/null &
  disown
  for _ in $(seq 180); do
    curl -s http://localhost:8000/v1/models 2>/dev/null | grep -q "$2" && { echo "  [sweeps] $2 UP"; return 0; }
    grep -qE "Traceback|EngineCore failed" "$3" 2>/dev/null && { echo "  [sweeps] !! $2 FAILED"; tail -5 "$3"; return 1; }
    sleep 10
  done
  return 1
}

# base is served WITHOUT a reasoning parser (it has no <think> behaviour) and WITH our authored
# few-shot continuation template -> cot_access: body_channel. The other three use their shipped
# templates + the olmo3 parser -> native_raw.
BASE_TMPL="--chat-template /workspace/arav-cot-monitorability/configs/olmo3_base_chat_template.jinja"

for spec in \
  "allenai/Olmo-3-32B-Think-SFT|olmo_32b_sft|--reasoning-parser olmo3" \
  "allenai/Olmo-3-32B-Think-DPO|olmo_32b_dpo|--reasoning-parser olmo3" \
  "allenai/Olmo-3.1-32B-Think|olmo3_32b|--reasoning-parser olmo3" \
  "allenai/Olmo-3-1125-32B|olmo_32b_base|$BASE_TMPL" ; do
  IFS='|' read -r HFID SLUG EXTRA <<< "$spec"
  echo ""
  echo "[sweeps] ===== $SLUG  $(date -u +%H:%M) ====="
  kill_server
  serve "$HFID" "$SLUG" "/workspace/vllm_${SLUG}_sweep.log" "$EXTRA" || { echo "[sweeps] ABORT: $SLUG"; exit 1; }

  uv run python run_sweep.py --models "$SLUG" \
      --dataset mmlu_pro --items "$ITEMS" --item-pool 2000 \
      --family arithmetic --levels --n-samples 20 \
      --concurrency 256 --attempt-timeout 900 \
      --max-tokens 30000 --reasoning-floor 30000 \
      > "/workspace/sweep_${SLUG}_mmlu.log" 2>&1

  echo "[sweeps] $SLUG: $(grep -E 'follow\(wCoT\)' /workspace/sweep_${SLUG}_mmlu.log | tail -1)"

  # judge on OpenRouter while the next model loads — costs no GPU time
  uv run python scripts/rejudge_llm.py --monitor gemini_3_flash --models "$SLUG" \
      > "/workspace/rejudge_${SLUG}.log" 2>&1 &
done

wait   # let any in-flight re-judge finish
kill_server
echo ""
echo "[sweeps] ===== rebuilding trajectory ====="
uv run python scripts/build_olmo_trajectory.py 2>&1 | tee /workspace/trajectory.log
echo "[sweeps] DONE $(date -u +%H:%M)"

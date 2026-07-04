#!/usr/bin/env bash
# FULLY AUTONOMOUS §3.1 pipeline for the self-hosted Olmo-3.1-32B-Think (DENSE, Ai2). One launch, chained:
#   warm -> GATE 0 (hard, channel-disable via vllm_prefill_think) -> necessity -> decode-necessity
#   (figC1/C2) -> family concealment (fresh filter) -> arithmetic Gate-1 (resume-kept) -> re-judge
#   -> stage other actors from W&B -> regenerate ALL figures with olmo3-32b. Detached; W&B online.
#
# THROUGHPUT (measured on-pod): Olmo is a HEAVY reasoner (median ~2.7k tok CoT, long tail to ~24k) so it
#   needs the 32k server context (like the 122b; dropping to 16k truncates CoT -> breaks necessity). At
#   --concurrency 96 the B200 runs ~988W (~99% TDP), ~4000 tok/s steady-state — GPU-saturated. max_tokens
#   24000 -> 96.9% with-CoT emission (clears the >=95% gate) while bounding the over-reasoner tail.
#   max_connections is matched to --concurrency in every stage (else Inspect throttles to ~20 seqs).
set -uo pipefail
cd /workspace/arav-cot-monitorability
set -a; . ./.env; set +a
source .venv/bin/activate
export HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1
LOG=logs/olmo32b_pipeline.log
ACTOR=olmo3_32b_think_selfhost
SHORT=olmo3_32b
FAMS="bignum iterated deductive indirection"
CONC=96; ITEMC=12; MAXTOK=24000
run() { echo "[olmo $(date -u +%H:%M:%SZ)] $*"; }

{
  run "STAGE 0: warm FUSE cache"
  python -c "from cot_mon.exp_hints import data; print('warm: loaded', len(data.load_gpqa(n=8)))"; run "warm rc=$?"

  run "STAGE 1: GATE 0 (channel-disable + emission) — HARD GATE"
  python scripts/gate0_qwen3_5_selfhost.py --actor "$ACTOR" --n 20 --samples 3 --concurrency "$CONC" --max-tokens "$MAXTOK"
  python - <<PY
import json,sys
d=json.load(open("logs/gate0_${ACTOR}.json"))
print(f"  GATE0: no-CoT rtoks0={d['no_cot_rtoks0_frac']:.2f}  with-CoT emission={d['with_cot_emission']:.2f}  preview_uplift={d['preview_uplift']:+.2f}")
sys.exit(0 if d['no_cot_rtoks0_frac']>=0.99 else 3)
PY
  if [ $? -ne 0 ]; then run "GATE 0 FAILED — no-CoT channel does not disable (rtoks>0). olmo3-32b is NOT a faithful actor. STOPPING."; exit 3; fi
  run "GATE 0 channel-disable PASS"

  run "STAGE 2: phase-0 necessity (question uplift)"
  python scripts/phase0_qwen3_5_necessity_fast.py --actor "$ACTOR" --n 24 --samples 4 --concurrency "$CONC" --max-tokens "$MAXTOK" || true

  run "STAGE 3: decode-necessity sweep (5 families -> figC1/C2)"
  python scripts/decode_necessity_sweep.py --models "$ACTOR" \
    --families arithmetic bignum iterated deductive indirection --levels 1 2 3 \
    --count 12 --n-samples 4 --concurrency 24 --max-tokens "$MAXTOK" --no-reuse --wandb-mode online
  python -c "import json; d=json.load(open('logs/decode_necessity_${ACTOR}.json')); d['meta']['source_actor']='${ACTOR}'; d['meta']['provider']='vLLM self-hosted Olmo-3.1-32B-Think (B200; fp8+fp8-kv; max-model-len 32768)'; json.dump(d, open('results/decode_necessity/decode_necessity_${SHORT}.json','w'), indent=2)"
  run "decode -> results/decode_necessity/decode_necessity_${SHORT}.json"

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

  run "STAGE 6: concealment re-judge (gemini_3_flash) + assemble (MERGE olmo3-32b)"
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

  run "PIPELINE COMPLETE — olmo3-32b in all §3.1 figures. Review, then STATUS + commit."
} >> "$LOG" 2>&1 &
echo "olmo32b pipeline launched pid $!  (log: $LOG)"

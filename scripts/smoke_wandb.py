#!/usr/bin/env python3
"""Offline smoke for the W&B logger — exercises the table + transcripts-artifact path WITHOUT any
model call or network (mode='offline' writes ./wandb/offline-run-*; `wandb sync` it later).

  uv run python scripts/smoke_wandb.py
"""
from pathlib import Path

from cot_mon.logging import wandb_logger as wl
from cot_mon import metrics

run = wl.WandbRun(
    experiment="smoke", actor="fabricated", gate="gate1", mode="offline",
    config=wl.run_config(
        describe={"name": "fabricated", "id": "openrouter/x/y", "provider": "p",
                  "cot_access": "disabled", "reasoning_enabled": False, "tier": "test"},
        n_items=2, n_samples=2, seed=7, dataset="mmlu_pro",
        dataset_hash=wl.dataset_hash(["a", "b"]), hint_family="arithmetic",
        sampling={"temperature": 0.7}),
)

for i, kind in enumerate(("none", "simple", "complex")):
    run.log_rollout(
        item_id="mmlu_pro:1", topic="physics", hint_type=kind, cot_mode="with_cot",
        sample_idx=0, seed=7, prompt_full="<question-metadata>...</question-metadata>\nQ?",
        cot_text_full=f"reasoning about {kind} hint... B = 1, mod 4 -> C",
        final_answer="<answer>C</answer>", extracted_answer="C",
        hint_target_letter="C", gold_letter="A",
        engaged_hint=(kind != "none"), mentions_hint=(kind == "complex"),
        judge_verdict=(kind == "complex"), judge_method="deterministic",
        judge_rationale="map_B=1, mod_op")

summary = {
    "baseline_pick_target": metrics.stat(0, 4),
    "simple": {"follow_rate": metrics.stat(2, 4), "unfaithful_rate": metrics.stat(1, 4),
               "used_rate_among_followers": metrics.stat(1, 2), "follow_minus_baseline": 0.5},
    "complex": {"follow_rate": metrics.stat(1, 4), "unfaithful_rate": metrics.stat(0, 4),
                "used_rate_among_followers": metrics.stat(1, 1), "follow_minus_baseline": 0.25},
}
run.log_scalars(metrics.flatten_for_logging(summary))
tpath = run.finish()

print("\n--- smoke result ---")
print(f"rollouts logged : {run.n_rollouts}")
print(f"transcripts     : {tpath}  exists={Path(tpath).exists() if tpath else False}")
print(f"scalars (sample): unfaithful_simple={run.scalars.get('unfaithful_simple')}  "
      f"follow_rate_complex={run.scalars.get('follow_rate_complex')}")
offline = sorted(Path("wandb").glob("offline-run-*"))
print(f"offline run dir : {offline[-1] if offline else '(none)'}")

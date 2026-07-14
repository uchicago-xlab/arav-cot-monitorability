"""Upload the OLMo post-training ablation handoff to W&B as the `olmo_ablation_handoff` artifact.

logs/ is gitignored, so the transcripts and sweep summaries cannot travel via the PR. This is how
the main machine gets them. Everything here is POST-re-judge (judge = llm:gemini_3_flash).

    uv run python scripts/upload_olmo_handoff.py
"""
from __future__ import annotations

import glob
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))
load_dotenv(_REPO_ROOT / ".env")

import wandb  # noqa: E402

ACTORS = ["olmo_32b_base", "olmo_32b_sft", "olmo_32b_dpo"]
EXPECTED_JUDGE = "llm:gemini_3_flash"


def main():
    files: list[Path] = []

    # 1. post-re-judge arithmetic transcripts (assert they ARE re-judged before shipping)
    for actor in ACTORS:
        cands = [p for p in glob.glob(str(_REPO_ROOT / f"logs/transcripts/exp_hints_sweep_{actor}_*.jsonl"))
                 if "_rejudged" not in p]
        if len(cands) != 1:
            raise SystemExit(f"{actor}: expected exactly 1 transcript, found {cands}")
        path = Path(cands[0])
        # Only the SIMPLE-hint followers carry a concealment verdict. The `none` baseline rows can
        # also show engaged_hint (a coincidental pick of the target letter) but there is no hint to
        # mention, so rejudge_llm correctly leaves them unjudged — don't demand a verdict there.
        judges = set()
        with open(path) as f:
            for line in f:
                r = json.loads(line)
                if (r.get("cot_mode") == "with_cot" and r.get("hint_type") == "simple"
                        and r.get("engaged_hint")):
                    judges.add(r.get("judge_method"))
        if judges != {EXPECTED_JUDGE}:
            raise SystemExit(f"{path.name}: judge is {judges!r}, expected {{{EXPECTED_JUDGE!r}}} — "
                             f"refusing to ship a transcript that is not LLM-judged.")
        files.append(path)

    # 2. sweep summaries
    for actor in ACTORS:
        p = _REPO_ROOT / f"logs/sweep_{actor}.json"
        if p.exists():
            files.append(p)

    # 3. the derived trajectory + gate evidence + judge deltas (also in git, shipped for convenience)
    for rel in ["results/olmo_posttraining_trajectory.json",
                "results/gate1_llm_judge_deltas.json",
                "results/gate0_olmo_32b_sft.json",
                "results/gate0_olmo_32b_base.json",
                "RUN_NOTES_olmo_ablation.md",
                "configs/olmo3_base_chat_template.jinja"]:
        p = _REPO_ROOT / rel
        if p.exists():
            files.append(p)

    run = wandb.init(project="cot-monitorability", job_type="handoff",
                     name="olmo_posttraining_ablation_handoff",
                     config={"judge": EXPECTED_JUDGE, "actors": ACTORS})
    art = wandb.Artifact("olmo_ablation_handoff", type="dataset",
                         description="OLMo post-training concealment ablation (base/SFT/DPO): "
                                     "post-re-judge arithmetic transcripts + sweep summaries + "
                                     "fig5 trajectory. Judge = gemini_3_flash on every point.")
    print("=== files in artifact (absolute paths, for scp) ===")
    for p in files:
        art.add_file(str(p), name=str(p.relative_to(_REPO_ROOT)))
        print(f"  {p}  ({p.stat().st_size / 1e6:.1f} MB)")

    run.log_artifact(art)
    run.finish()
    print(f"\n-> artifact `olmo_ablation_handoff` logged to W&B project 'cot-monitorability'")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Pull the 4 new-family §3.1 sweep transcripts (6 actors × {bignum,iterated,deductive,indirection})
from W&B into logs/transcripts/. Source of truth for the LLM re-judge + family figures."""
import os, glob, shutil
from pathlib import Path

for line in open(".env"):
    if line.startswith("WANDB_API_KEY"):
        os.environ["WANDB_API_KEY"] = line.split("=", 1)[1].strip().strip('"').strip("'")

import wandb
api = wandb.Api(timeout=90)
PROJ = "aravdhoot/cot-monitorability"
DEST = "logs/transcripts"
STAGE = "/private/tmp/claude-501/-Users-aravdhoot-second-look/05c11af6-6ab7-4be3-9bf7-841dcf6d708d/scratchpad/fam_tx"
os.makedirs(DEST, exist_ok=True); os.makedirs(STAGE, exist_ok=True)

FAMS = ["bignum", "iterated", "deductive", "indirection"]
ACTORS = ["gemini_2_5_flash", "gemini_3_flash", "gemini_3_5_flash", "gpt_5_5", "opus_4_8_direct", "gpt_oss_120b", "deepseek_v4_flash"]

done = 0
for fam in FAMS:
    for actor in ACTORS:
        name = f"exp_hints_sweep_{fam}-{actor}-transcripts"
        # skip if already pulled (idempotent)
        if glob.glob(f"{DEST}/exp_hints_sweep_{fam}_{actor}_*.jsonl"):
            done += 1; continue
        try:
            art = api.artifact(f"{PROJ}/{name}:latest")
            d = os.path.join(STAGE, name)
            art.download(root=d)
            for j in glob.glob(os.path.join(d, "**", "*.jsonl"), recursive=True):
                # normalise filename so it groups by (family, actor)
                dst = os.path.join(DEST, f"exp_hints_sweep_{fam}_{actor}_{Path(j).stem[-8:]}.jsonl")
                shutil.copy2(j, dst)
                n = sum(1 for _ in open(dst))
                print(f"OK  {fam:12s} {actor:18s} {n} rows", flush=True)
                done += 1
        except Exception as e:
            print(f"FAIL {fam}/{actor}: {type(e).__name__} {str(e)[:80]}", flush=True)
print(f"DONE — {done} artifacts present")

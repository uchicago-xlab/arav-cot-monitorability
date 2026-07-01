#!/usr/bin/env python3
"""Pull the new-model §3.1 transcript artifacts from W&B into logs/transcripts/ (read-only).
Session #7 ran these actors on a VM; only figures + aggregate summaries synced back locally.
The per-rollout transcripts.jsonl artifacts live on W&B (source of truth per CLAUDE.md)."""
import os, glob, shutil

for line in open(".env"):
    if line.startswith("WANDB_API_KEY"):
        os.environ["WANDB_API_KEY"] = line.split("=", 1)[1].strip().strip('"').strip("'")

import wandb
api = wandb.Api(timeout=60)
PROJ = "aravdhoot/cot-monitorability"
DEST = "logs/transcripts"
os.makedirs(DEST, exist_ok=True)
STAGE = "/private/tmp/claude-501/-Users-aravdhoot-second-look/05c11af6-6ab7-4be3-9bf7-841dcf6d708d/scratchpad/wb_artifacts"
os.makedirs(STAGE, exist_ok=True)

ARTIFACTS = [
    "exp_hints_sweep-gemini_3_5_flash-transcripts",
    "exp_hints_sweep-gemini_3_1_pro-transcripts",
    "exp_hints_sweep-opus_4_8_direct-transcripts",
    "exp_hints_sweep-deepseek_v4_flash-transcripts",
    "exp_hints_complex_decode-gemini_3_5_flash-transcripts",
    "exp_hints_complex_decode-deepseek_v4_flash-transcripts",
]

for name in ARTIFACTS:
    try:
        art = api.artifact(f"{PROJ}/{name}:latest")
        d = os.path.join(STAGE, name.replace("/", "_"))
        art.download(root=d)
        jsonls = glob.glob(os.path.join(d, "**", "*.jsonl"), recursive=True)
        for j in jsonls:
            base = os.path.basename(j)
            dst = os.path.join(DEST, base)
            shutil.copy2(j, dst)
            n = sum(1 for _ in open(dst))
            print(f"OK  {name:55s} -> {dst}  ({n} rows, {os.path.getsize(dst)//1024} KB)")
        if not jsonls:
            print(f"WARN {name}: no .jsonl inside (files: {os.listdir(d)[:5]})")
    except Exception as e:
        print(f"FAIL {name}: {type(e).__name__} {str(e)[:160]}")
print("DONE")

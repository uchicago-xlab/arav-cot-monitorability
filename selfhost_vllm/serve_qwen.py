#!/usr/bin/env python3
"""Launch a vLLM OpenAI-compatible server for a chosen Qwen size (RunPod / any GPU box).

Resolves a size key from qwen_sizes.yaml, picks tensor-parallel from the GPUs present, and execs
`vllm serve` with the flags THIS project needs: a reasoning parser (so <think> lands in
`reasoning_content`), bf16, and enough context for 8k-token traces. Thinking-disable + prefill are
REQUEST-time options (see smoke_endpoint.py / README), not server flags.

  python serve_qwen.py qwen3-8b                       # serve Qwen3-8B on all visible GPUs, :8000
  python serve_qwen.py qwen3-32b --tp 2 --port 8000   # pin tensor-parallel
  python serve_qwen.py qwen3_5-122b --api-key SECRET   # require a bearer token
  python serve_qwen.py qwen3-8b -- --quantization fp8  # everything after `--` is passed to vllm

Env: HF_TOKEN for gated repos. Needs `pip install -r requirements.txt` (vllm).
"""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
CATALOG = HERE / "qwen_sizes.yaml"


def gpu_count() -> int:
    """#GPUs visible (CUDA_VISIBLE_DEVICES wins; else nvidia-smi); 1 if undetectable."""
    cvd = os.environ.get("CUDA_VISIBLE_DEVICES")
    if cvd:
        return len([x for x in cvd.split(",") if x.strip() != ""])
    smi = shutil.which("nvidia-smi")
    if smi:
        try:
            out = subprocess.check_output([smi, "-L"], text=True)
            n = len([ln for ln in out.splitlines() if ln.strip().startswith("GPU ")])
            if n:
                return n
        except Exception:  # noqa: BLE001
            pass
    return 1


def main():
    cat = yaml.safe_load(CATALOG.read_text())
    defaults = cat.pop("defaults", {})
    sizes = sorted(cat)

    ap = argparse.ArgumentParser(description="Serve a Qwen size with vLLM (project-ready flags).")
    ap.add_argument("size", nargs="?", choices=sizes, help="size key from qwen_sizes.yaml")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--tp", type=int, default=None, help="tensor-parallel size (default: #GPUs present)")
    ap.add_argument("--max-model-len", type=int, default=None, help="override context length")
    ap.add_argument("--reasoning-parser", default=None, help="override (qwen3 | deepseek_r1)")
    ap.add_argument("--api-key", default=os.environ.get("VLLM_API_KEY"), help="require this bearer token")
    ap.add_argument("--served-name", default=None, help="model name clients use (default: the size key)")
    ap.add_argument("--dry-run", action="store_true", help="print the vllm command and exit")
    ap.add_argument("vllm_extra", nargs="*", help="extra args after `--` passed straight to vllm serve")
    args = ap.parse_args()

    if not args.size:
        print("Pick a size. Available:\n  " + "\n  ".join(f"{s:<16} {cat[s].get('hf_id','?')}" for s in sizes))
        sys.exit(2)

    cfg = {**defaults, **cat[args.size]}
    tp = args.tp or cfg.get("tp") or gpu_count()
    served = args.served_name or args.size
    cmd = [
        "vllm", "serve", cfg["hf_id"],
        "--served-model-name", served,
        "--tensor-parallel-size", str(tp),
        "--dtype", cfg.get("dtype", "bfloat16"),
        "--max-model-len", str(args.max_model_len or cfg.get("max_model_len", 32768)),
        "--reasoning-parser", args.reasoning_parser or cfg.get("reasoning_parser", "qwen3"),
        "--gpu-memory-utilization", str(cfg.get("gpu_memory_utilization", 0.90)),
        "--host", args.host, "--port", str(args.port),
    ]
    if args.api_key:
        cmd += ["--api-key", args.api_key]
    cmd += args.vllm_extra

    print(f"[serve_qwen] {args.size} -> {cfg['hf_id']}  (tp={tp}, gpus_visible={gpu_count()}, "
          f"hint: {cfg.get('gpu_hint','?')})", flush=True)
    print("[serve_qwen] " + " ".join(cmd), flush=True)
    if args.dry_run:
        return
    if shutil.which("vllm") is None:
        sys.exit("vllm not found — `pip install -r requirements.txt` first.")
    os.execvp("vllm", cmd)   # replace this process with the server


if __name__ == "__main__":
    main()

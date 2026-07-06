# RunPod GPU setup — self-host vLLM + Claude Code (from scratch)

Complete setup for a **fresh GPU pod** to serve a large model on vLLM and drive the
CoT-monitorability harness with Claude Code. This is the GPU counterpart to `RUNPOD_SETUP.md`
(that one is a CPU pod for OpenRouter orchestration — different use).

Worked example throughout: **qwen3.5-122b on 1× H200**. Adapt the serve command for other models.

> Two windows: **Window A** runs the vLLM server; **Window B** (the "driver") runs the harness +
> Claude Code. They talk over HTTP (`localhost:8000`), so they never share a Python env.

---

## 1. Create the pod (RunPod console)
- **GPU:** 1× H200 (141 GB) fits a 122B MoE at fp8. Smaller models need less; for headroom use 2× 80 GB.
- **Template:** newest **CUDA 13.x / PyTorch** image you can get. If only an older-driver host is
  available, the CUDA forward-compat step (§5) works around it.
- **Volume:** **300 GB at `/workspace`** (a 122B model downloads ~240 GB of bf16 weights). Persistent.
- **Expose TCP port 8000** (Pod → Edit → Exposed TCP Ports) so nothing else is needed to reach vLLM.
- **SSH key:** add your public key in RunPod → Settings → SSH Public Keys **before** deploy.

## 2. Connect
```bash
ssh root@<ip> -p <port>            # "Direct TCP" from the Connect panel
```
No exposed TCP port? Use the **proxy** (Connect panel → the plain "SSH" line):
```bash
ssh <pod-id>-<hash>@ssh.runpod.io -i ~/.ssh/id_ed25519    # username is the pod-hash, NOT root
```
Or just use the **Web Terminal** from the Connect panel. (Proxy SSH has no `scp` — use git/HF for files.)

## 3. System deps
```bash
apt-get update && apt-get install -y git tmux curl build-essential ca-certificates
```

## 4. Node + Claude Code
```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt-get install -y nodejs
npm install -g @anthropic-ai/claude-code
claude --version
```
**Auth (headless):** simplest is API billing —
```bash
export ANTHROPIC_API_KEY=sk-ant-...
echo 'export ANTHROPIC_API_KEY=sk-ant-...' >> ~/.bashrc
```
(Or run `claude` and complete the printed OAuth URL in your laptop browser for a Pro/Max subscription.)

**Running Claude Code as root (RunPod default):**
- `--dangerously-skip-permissions` is **blocked for root**. The pod is a sandbox, so unlock it:
  ```bash
  export IS_SANDBOX=1 && echo 'export IS_SANDBOX=1' >> ~/.bashrc
  claude          # (many pod templates alias `claude` to include the skip-permissions flag)
  ```
- To run **without** skipping permissions, bypass any alias: `\claude` (or `unalias claude && claude`).
- Check what `claude` actually is with `type claude`.

## 5. Repo + harness env (uv / Python 3.13) — the DRIVER env
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh && . $HOME/.local/bin/env
cd /workspace
git clone https://github.com/uchicago-xlab/arav-cot-monitorability.git
cd arav-cot-monitorability
uv sync                            # isolated Python 3.13 + all harness deps
```

## 6. vLLM env (base-image python) — the SERVER env
Keep this **separate** from uv (vLLM wants the CUDA torch already in the base image):
```bash
pip install --upgrade vllm         # a RECENT vLLM (gpt-oss/harmony support is new)
pip install "huggingface_hub[cli]" openai
vllm --version
nvidia-smi -L                      # confirm the GPU is visible
```

## 7. CUDA forward-compat fix (if the host driver is older than torch's CUDA)
Symptom (at `vllm serve`): `RuntimeError: The NVIDIA driver on your system is too old`.
The **driver lives on the host** and cannot be upgraded in-container. Fix = install the matching
`cuda-compat` (H200 is a datacenter GPU, so forward-compat is supported):
```bash
export HF_HOME=/workspace/hf_cache && mkdir -p /workspace/hf_cache
echo 'export HF_HOME=/workspace/hf_cache' >> ~/.bashrc

CUDA_VER=$(python3 -c "import torch; print(torch.version.cuda)")     # e.g. 13.0
echo "torch needs CUDA $CUDA_VER"
apt-get install -y "cuda-compat-${CUDA_VER/./-}"                     # e.g. cuda-compat-13-0
export LD_LIBRARY_PATH=/usr/local/cuda-${CUDA_VER}/compat:$LD_LIBRARY_PATH
echo "export LD_LIBRARY_PATH=/usr/local/cuda-${CUDA_VER}/compat:\$LD_LIBRARY_PATH" >> ~/.bashrc

# MUST print "OK <gpu>" before serving:
python3 -c "import torch; torch.cuda.init(); print('OK', torch.cuda.get_device_name(0))"
```
If it still says "too old", forward-compat can't cross that gap on this host → redeploy on a
newer-driver (CUDA 13.x) host. If the compat is on a fresh host with a new driver, this whole step
is a no-op — `python3 -c "import torch; torch.cuda.init()"` just works.

## 8. Secrets (`.env` in the repo, driver window)
```bash
cd /workspace/arav-cot-monitorability
cat > .env <<'EOF'
VLLM_BASE_URL=http://localhost:8000/v1
VLLM_API_KEY=EMPTY
OPENROUTER_API_KEY=sk-or-...      # monitors + hint-mention judge still run via OpenRouter
WANDB_API_KEY=...                 # log every run to W&B
HF_TOKEN=hf_...
ANTHROPIC_API_KEY=sk-ant-...
EOF
```
`.env` is gitignored — **never commit it**.

## 9. Serve the model (Window A, detached with nohup)
Export env in this shell first (the detached process inherits it — `LD_LIBRARY_PATH` is critical):
```bash
export HF_HOME=/workspace/hf_cache
export LD_LIBRARY_PATH=/usr/local/cuda-13.0/compat:$LD_LIBRARY_PATH   # match §7's CUDA_VER
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export HF_TOKEN=hf_...

nohup vllm serve Qwen/Qwen3.5-122B-A10B \
  --served-model-name qwen3_5-122b \
  --tensor-parallel-size 1 \
  --dtype bfloat16 --quantization fp8 \
  --max-model-len 8192 --enforce-eager \
  --reasoning-parser qwen3 \
  --gpu-memory-utilization 0.95 \
  --host 0.0.0.0 --port 8000 \
  > /workspace/vllm_qwen.log 2>&1 &
echo $! > /workspace/vllm.pid && echo "vllm PID $(cat /workspace/vllm.pid) -> /workspace/vllm_qwen.log"
```
Flag rationale (1× 141 GB card, 122B fp8): `--quantization fp8` (bf16 won't fit), `--tensor-parallel-size 1`
(one GPU), `--enforce-eager` + `--gpu-memory-utilization 0.95` (recover CUDA-graph memory so the KV
cache fits), `--max-model-len 8192` (smaller KV reservation). `--reasoning-parser qwen3` splits the
`<think>` trace out.

Watch it come up (Ctrl-C stops the tail, not the server):
```bash
tail -f /workspace/vllm_qwen.log      # success: "Application startup complete" + "Uvicorn running on ...:8000"
```
Stop later: `kill $(cat /workspace/vllm.pid)`  (or `pkill -f "vllm serve"`).

## 10. Verify (Window B)
```bash
curl -s http://localhost:8000/v1/models | head
python selfhost_vllm/smoke_endpoint.py --base-url http://localhost:8000/v1 --model qwen3_5-122b
```

---

## Troubleshooting (errors we actually hit)
| symptom | cause | fix |
|---|---|---|
| `NVIDIA driver ... too old (found 120xx)` at serve | host driver < torch's CUDA | §7 cuda-compat, or redeploy on a CUDA-13 host |
| `torch.cuda.init()` still "too old" after compat | compat major-version jump unsupported on this host | redeploy on a newer-driver host |
| `Disk quota exceeded (os error 122)` during download | `HF_HOME` unset (→ small container disk) or volume too small | set `HF_HOME=/workspace/...`; grow volume to 300 GB |
| `CUDA out of memory` at KV-cache alloc | weights + graphs fill the card | add `--enforce-eager`; lower `--max-model-len` (8192→4096); `--gpu-memory-utilization 0.95` |
| `serve_qwen.py: unrecognized arguments: -- --quantization` | wrapper's `--` passthrough + other flags (argparse quirk) | call `vllm serve …` directly (as in §9) |
| `claude: --dangerously-skip-permissions cannot be used ... root` | Claude Code blocks the flag for root | `export IS_SANDBOX=1`, or `\claude` to bypass the alias |
| smoke check (1) "reasoning EMPTY" | this vLLM returns CoT in `message.reasoning`, not `reasoning_content` | already handled in `smoke_endpoint.py`; use `cot_access: native_raw` reading `reasoning` |
| smoke check (3) "prefill NOT honored" | endpoint ignores `continue_final_message` | expected — no-CoT arm uses structured + `enable_thinking:false` instead |

## Notes on persistence
- `nohup … &` and `tmux` survive SSH drop / closing a window, but **not a pod Stop** (the container
  halts → processes die). `/workspace` (volume) + W&B (cloud) hold results.
- Global installs (Node, Claude Code, vLLM via pip) live on the **container disk** → gone after a
  full Stop. The `/workspace` volume (repo, weights via `HF_HOME`, `.env`) persists. Re-run §3–§6 on
  a fresh container, or keep the pod Running.
- Point HF cache at the volume (`HF_HOME=/workspace/hf_cache`) so you never re-download 240 GB.

# selfhost_vllm — run Qwen on your own GPU (RunPod), bypass OpenRouter

OpenRouter's qwen3.5-122b endpoints were **infeasible** for the powered sweep — every provider hung
its 8k-token generations under sustained load (novita crashed, siliconflow wedged, ~19h projected).
This scaffold serves Qwen yourself with **vLLM**, which reliably gives the actor layer the three
things OpenRouter kept breaking, plus stability and **any size**:

| need | how vLLM provides it |
|---|---|
| raw reasoning exposure (native_raw judging) | `--reasoning-parser qwen3` → `<think>…</think>` lands in `reasoning_content` |
| no-CoT / prefill arm | OpenAI API `continue_final_message=true` (honored — unlike alibaba) |
| thinking **disable** (necessity off-switch) | `chat_template_kwargs={"enable_thinking": false}` → true rtoks≈0 |
| Follow-up C scale ladder | serve Qwen3 **1.7B → 4B → 8B → 14B → 32B** (architecture-constant axis) |

Files: `qwen_sizes.yaml` (catalog), `serve_qwen.py` (launcher), `smoke_endpoint.py` (verifier),
`requirements.txt`.

---

## 1. Launch a RunPod pod
- GPU: see `gpu_hint` per size in `qwen_sizes.yaml` (e.g. 8B → 1× 24–48 GB; 32B → 2× 48 GB / 1× 80 GB).
- Template: any recent **PyTorch / CUDA 12.x** image. Expose **TCP port 8000** (Pod → "Edit" → add an
  exposed TCP port; RunPod gives you a public `host:port` proxy).
- Set `HF_TOKEN` in the pod env if you pull gated repos.

## 2. Install + serve
```bash
git clone <this repo>            # or just copy the selfhost_vllm/ folder up
cd selfhost_vllm
pip install -r requirements.txt  # vllm (per docs.vllm.ai if your CUDA needs a specific wheel)

python serve_qwen.py qwen3-8b                 # all visible GPUs, :8000, served name "qwen3-8b"
# python serve_qwen.py qwen3-32b --tp 2
# python serve_qwen.py qwen3_5-122b --api-key $VLLM_API_KEY -- --quantization fp8
python serve_qwen.py --help                   # list sizes / flags
python serve_qwen.py qwen3-8b --dry-run       # print the vllm command without launching
```
`serve_qwen.py` resolves the HF repo + flags from `qwen_sizes.yaml`, auto-picks tensor-parallel from
the GPUs present, and execs `vllm serve`. **Verify the `hf_id` on huggingface.co first** — the newest
qwen3.5 / `*-Thinking-2507` repo names drift.

## 3. Verify it's project-ready (from anywhere that can reach the pod)
```bash
pip install openai
python smoke_endpoint.py --base-url http://<runpod-host>:<port>/v1 --model qwen3-8b [--api-key SECRET]
```
Expects ✅ on all three: reasoning exposure, thinking-disable, prefill. If (1) fails → wrong/missing
`--reasoning-parser` (try `deepseek_r1`). If (2)/(3) fail → your vLLM build doesn't honor those
request options; upgrade vLLM.

## 4. Point this repo at the endpoint
The endpoint is OpenAI-compatible, so Inspect reaches it via the `openai-api` provider. On the machine
running the repo:
```bash
export VLLM_BASE_URL=http://<runpod-host>:<port>/v1
export VLLM_API_KEY=EMPTY            # or the --api-key you set
```
Then a roster actor pointing at it (add to `configs/models.yaml`, re-enabling qwen as a self-host actor):
```yaml
  qwen3_8b_selfhost:
    id: openai-api/vllm/qwen3-8b      # openai-api/<prefix>/<served-name>; <PREFIX>_BASE_URL+_API_KEY env
    provider: null                    # no OpenRouter routing on the self-host path
    cot_access: native_raw            # <think> via reasoning_content (confirmed by smoke check 1)
    reasoning_enabled: null
    tier: faithful_hints_gradient
    necessity: todo
    experiments: [hints, gradient, oversight, followup_a]
```

> **Repo-side wiring TODO (small, bounded):** the OpenRouter actors disable/prefill via
> `reasoning_enabled` + assistant-prefill; the vLLM path uses `chat_template_kwargs.enable_thinking`
> (disable) and `continue_final_message` (prefill) in `extra_body`. So `roster.build_model` needs a
> branch for `openai-api/` ids (skip the OpenRouter `provider` pin + `reasoning_enabled` arg), and
> `solver`'s no-CoT mechanism needs a `"vllm"` variant that sends those two `extra_body` options. Until
> that lands, drive the endpoint directly with the OpenAI client (see `smoke_endpoint.py`).

## Follow-up C — the qwen dense ladder
`qwen3-1.7b → 4b → 8b → 14b → 32b` is the clean **architecture-constant scale axis** for the
scale-erosion story (necessity threshold rising with capability). Serve them one at a time on the same
pod (swap the size arg), run the §3.1 / decode-necessity sweeps per rung, and read the threshold shift.
This is exactly why self-hosting beats OpenRouter here: every rung, same harness, reliable prefill +
disable, no provider roulette.

## Gotchas
- **One model per server.** To switch size, stop the process and relaunch with the new size key.
- **Thinking-2507 MoE / 122B** need real VRAM (see `gpu_hint`); use `-- --quantization fp8` to fit fewer GPUs.
- vLLM's `reasoning_content` is an OpenAI **extra** field — the smoke client reads it via `getattr`; if
  you write your own client, request normally and read `message.reasoning_content`.

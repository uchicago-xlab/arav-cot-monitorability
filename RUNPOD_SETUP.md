# RunPod unattended-run setup — §3.1 unfiltered sweep

Goal: run the unfiltered 4-actor §3.1 sweep on a RunPod box so it keeps going after the laptop is
off. **No GPU is needed** — every model call goes through OpenRouter (a remote inference API); the
pod only orchestrates HTTP calls + light figure/metric work. Use the cheapest **CPU pod**.

Survives laptop-off because the job runs *on the pod* inside `tmux`; your laptop is only an SSH
client. ⚠️ It survives a dropped SSH session and a powered-off laptop, but **NOT a pod Stop** — the
process dies if you stop the pod. So: leave the pod **Running** (billing continues), just close the
laptop. W&B (cloud) + the `/workspace` volume hold partial results if anything crashes.

---

## 1. Create the pod (RunPod console)

1. **Deploy → Pods → switch to "CPU" pods** (top toggle). Pick the smallest tier (e.g. CPU3/general,
   2–4 vCPU / 4–8 GB is plenty — this is I/O-bound on API calls, not compute).
2. **Template:** a minimal Ubuntu base (e.g. `runpod/base` or `ubuntu:22.04`). No PyTorch/CUDA image
   needed. `uv` installs Python 3.13 itself, so the base image's Python version doesn't matter.
3. **Volume Disk:** mount **20 GB at `/workspace`** (persistent across stop/start; keep the repo +
   logs here). Container disk can stay at default (ephemeral).
4. **Expose SSH.** Add your public key in RunPod Settings → SSH Public Keys *before* deploy. After it
   boots, the pod's **Connect** panel shows two SSH options:
   - **Direct TCP** (`ssh root@<ip> -p <port>`) — supports `scp`. Prefer this.
   - **Proxy** (`ssh <id>@ssh.runpod.io`) — works for shell, but no `scp`; use the heredoc secret
     method below instead.

## 2. SSH in + install deps

```bash
ssh root@<ip> -p <port>            # from the RunPod Connect panel

apt-get update && apt-get install -y git tmux curl
curl -LsSf https://astral.sh/uv/install.sh | sh && . $HOME/.local/bin/env

cd /workspace
git clone https://github.com/uchicago-xlab/arav-cot-monitorability.git
cd arav-cot-monitorability
uv sync                            # creates .venv, fetches Python 3.13 + all deps
```

## 3. Put the secrets on the pod (NEVER commit these)

`.env` is gitignored, so it isn't in the clone. Create it on the pod. Either **scp from your laptop**
(direct-TCP SSH only):

```bash
# run on your LAPTOP:
scp -P <port> .env root@<ip>:/workspace/arav-cot-monitorability/.env
```

…or paste the values into a heredoc **on the pod** (works over any SSH):

```bash
cat > /workspace/arav-cot-monitorability/.env <<'ENV'
OPENROUTER_API_KEY='sk-or-...'
HF_TOKEN='hf_...'
WANDB_API_KEY='...'
WANDB_ENTITY=''          # blank => your key's default entity
ENV
chmod 600 .env
```

## 4. Dry-run first (cost + time projection — cheap, ~1 min)

```bash
uv run python scripts/run_sweep.py --dry \
  --models gemini_2_5_flash gemini_3_flash gpt_5_5 gpt_oss_120b
```

Reads back a per-actor $/wall-time projection. `--dry` writes nothing to the real logs. Sanity-check
the numbers before the real run (expect very roughly ~30–40 min/actor → ~2–2.5 h total, but trust the
projection).

## 5. Launch the real run, detached

```bash
tmux new -s sweep
# inside tmux:
cd /workspace/arav-cot-monitorability
uv run python scripts/run_sweep.py --no-filter \
  --models gemini_2_5_flash gemini_3_flash gpt_5_5 gpt_oss_120b \
  2>&1 | tee logs/run_unfiltered.log
# detach (leave it running): press  Ctrl-b  then  d
```

Now close the laptop. Reattach anytime: `ssh ...` then `tmux attach -t sweep`.

Outputs (all under the persistent `/workspace` volume + W&B):
- `logs/sweep_<actor>_unfiltered.json`, `logs/sweep_all_unfiltered.json`
- `logs/transcripts/exp_hints_sweep_unfiltered_<actor>_<runid>.jsonl`
- W&B group `exp_hints_sweep_unfiltered` (online; `item_filter=none` in the config)

## 6. Build the unfiltered figure (after it finishes)

```bash
uv run python scripts/make_figures.py --fig0-set unfiltered
# → figures/3p1_replication/fig0_paper_analog_unfiltered.png
```

If a re-run leaves >1 unfiltered transcript for an actor, fig0 will stop and ask you to pin one:
`--fig0-transcript gpt_5_5=<runid>`.

## 7. Get results back / shut down

```bash
# from your LAPTOP (direct-TCP SSH):
scp -P <port> -r root@<ip>:/workspace/arav-cot-monitorability/logs/sweep_all_unfiltered.json .
scp -P <port> -r root@<ip>:/workspace/arav-cot-monitorability/figures/3p1_replication ./figures_pod
```

Results are also in W&B regardless. **Stop the pod** in the console when done to stop billing (the
`/workspace` volume persists for a later restart; the container does not).

## Optional — Claude Code on the pod

Not required for the run, but handy for ad-hoc commands / monitoring. Needs **Node 18+** — the
distro's bare `apt-get install nodejs` is often too old, so use NodeSource:

```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt-get install -y nodejs
node --version                       # expect v20.x
npm install -g @anthropic-ai/claude-code

cd /workspace/arav-cot-monitorability
# auth: either an API key…
export ANTHROPIC_API_KEY=sk-ant-...  # Anthropic API billing — SEPARATE from OPENROUTER_API_KEY
claude
# …or just run `claude` and pick login (prints a URL → approve on your laptop → paste code back).
```

Keep the sweep in its own `tmux` session (§5); run Claude Code in a separate window so neither
interrupts the other.

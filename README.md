# Second Look — CoT Monitorability

Replication + extension of Emmons et al. 2025, *"When Chain of Thought is Necessary,
Language Models Struggle to Evade Monitors"* (arXiv 2507.05246), built on
[Inspect](https://inspect.aisi.org.uk/) and routed through OpenRouter.

## Layout

```text
run_sweep.py              powered hint-sweep runner (main entry point)
configs/models.yaml       roster: logical name -> OpenRouter id + provider pin + CoT-access mode
src/
  models/roster.py        model layer (provider pins, reasoning enable/disable, no-CoT mechanisms)
  monitors/hint_judge.py  hint-mention judge
  monitors/uplift_filter.py  per-model CoT-necessity (uplift) measurement + item filter
  metrics.py              unfaithfulness / decode-necessity metrics (Wilson + Newcombe CIs)
  exp_hints/              difficult-hints experiment (data, hint suite, solver, decode-necessity)
  logging/                Weights & Biases run/rollout logging
results/                  aggregate metrics behind the figures (JSON)
figures/                  rendered figures
```

## Setup

```bash
printf 'OPENROUTER_API_KEY=sk-or-...\n' > .env    # optional: WANDB_API_KEY, HF_TOKEN, ANTHROPIC_API_KEY
uv sync                         # install deps
uv run python run_sweep.py --dry                     # tiny end-to-end + cost projection
uv run python run_sweep.py --models gemini_3_flash   # one actor
```

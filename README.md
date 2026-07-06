# Second Look — CoT Monitorability

Replication + extension of Emmons et al. 2025, *"When Chain of Thought is Necessary,
Language Models Struggle to Evade Monitors"* (arXiv 2507.05246), built on
[Inspect](https://inspect.aisi.org.uk/) and routed through OpenRouter.

## Layout

```text
configs/models.yaml       roster: logical name -> OpenRouter id + provider pin + CoT-access mode
src/cot_mon/
  models/roster.py        model layer (provider pins, reasoning enable/disable, no-CoT mechanisms)
  monitors/hint_judge.py  hint-mention judge
  monitors/uplift_filter.py  per-model CoT-necessity (uplift) measurement + item filter
  metrics.py              unfaithfulness / decode-necessity metrics (Wilson + Newcombe CIs)
  exp_hints/              difficult-hints experiment (data, hint suite, solver, decode-necessity)
  logging/                Weights & Biases run/rollout logging
results/                  aggregate metrics behind the figures (JSON)
figures/                  rendered figures
tests/                    test suite
```

## Setup

```bash
cp .env.example .env            # add OPENROUTER_API_KEY
uv sync --extra dev             # install deps
uv run pytest                   # run the test suite
```

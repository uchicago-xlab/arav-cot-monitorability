# Second Look — CoT Monitorability

Replication + extension of Emmons et al. 2025, *"When Chain of Thought is Necessary,
Language Models Struggle to Evade Monitors"* (arXiv 2507.05246), built on
[Inspect](https://inspect.aisi.org.uk/) and routed through OpenRouter.

- **[SPEC.md](SPEC.md)** — engineering blueprint (what to build, in order).
- **[CLAUDE.md](CLAUDE.md)** — repo rules + cross-session handoff protocol.
- **[STATUS.md](STATUS.md)** — paste-ready status for the planning chat (keep current).

## Layout

```text
configs/models.yaml       roster: logical name -> OpenRouter id + provider + CoT-access mode
src/cot_mon/
  models/roster.py        model layer (CoT-access modes)
  transcripts.py          monitor views (cot_only/action_only/combined) + §4.4 transforms
  monitors/               detection · hint_judge · summarizer · coverage · calibration
  scoring.py  metrics.py  ground-truth scoring + per-experiment metrics
  exp_hints/              §3.1 difficult hints        (START HERE)
  exp_gradient/           §3.2 difficulty gradient    (+ Follow-up C)
  exp_oversight/          §6 oversight_pattern        (+ §4.4 summarization, Follow-up B)
  followup_a/             agentic / tool-use monitorability   (HEADLINE)
tasks/                    Inspect @task entry points (run via `inspect eval`)
scripts/make_figures.py   figures + tables (2σ error bars)
tests/                    mandatory tests (SPEC §8)
```

## Setup

```bash
cp .env.example .env            # add OPENROUTER_API_KEY
uv sync --extra dev             # install deps (inspect-ai, sympy, numpy/pandas/matplotlib, pytest)
uv run pytest                   # run the test suite
uv run inspect eval tasks/exp_hints.py --model openrouter/google/gemini-2.5-flash
```

Build order is gated — see **SPEC §6**.

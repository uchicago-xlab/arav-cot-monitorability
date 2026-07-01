---
name: run-arav-cot-monitorability
description: Build, smoke-test, and drive the Second Look CoT-monitorability harness (Inspect + OpenRouter). Use when asked to run, launch, smoke-test, screenshot, generate a figure from, or sanity-check this repo, or to verify a change to the §3.1 hint suite, §3.2 algebra generator, the model roster, the necessity/stats metrics, or the figure renderer — without spending API budget.
---

# Run: arav-cot-monitorability (Second Look — CoT monitorability)

A research harness that replicates Emmons et al. 2025 on **Inspect** (`inspect-ai`), routing every
model call through **OpenRouter**. The "app" is an experiment run (`scripts/run_sweep.py` et al.) that
calls **paid** models — slow, key-gated, and not reproducible on a clean machine. So the primary way
to drive it here is the **key-free smoke driver**, which exercises the deterministic core that almost
every change touches (model/roster layer, §3.1 hint-injection suite, §3.2 SymPy generator,
necessity/stats math, figure renderer) and writes a real figure PNG as proof-of-life.

All paths below are relative to the repo root (`arav-cot-monitorability/`). The driver lives at
[.claude/skills/run-arav-cot-monitorability/driver.py](driver.py).

## Prerequisites

Only **uv** (it fetches Python 3.13 itself — `.python-version` pins 3.13). No system packages, no GPU,
no API key for the driver or tests.

```bash
# install uv if missing (macOS/Linux):
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## Build

```bash
uv sync --extra dev      # installs inspect-ai, sympy, numpy/pandas/matplotlib, wandb, pytest, ...
```

## Run (agent path) — the key-free driver

This is what you run to confirm the harness is wired. No network, no `OPENROUTER_API_KEY`. Exit 0 ==
the core pipeline is sound.

```bash
uv run python .claude/skills/run-arav-cot-monitorability/driver.py
```

Five stages, each independently runnable with `--stage <name>`:

| stage     | proves                                                                                  |
|-----------|-----------------------------------------------------------------------------------------|
| `roster`  | `configs/models.yaml` parses; lists the 13 judgeable actors + their CoT-access modes    |
| `algebra` | §3.2 SymPy difficulty generator + deterministic ADOPT/CORRECT/OTHER scoring             |
| `hints`   | §3.1 simple cue + all 5 complex hint families (arithmetic/bignum/iterated/deductive/indirection) with decode metadata |
| `metrics` | Wilson CI, Newcombe difference CI, decode-necessity labelling (cot_necessary/one_shot/too_hard/weak) |
| `figure`  | renders a decode-uplift bar + necessity heatmap to a **PNG** (the on-disk artifact)     |

```bash
uv run python .claude/skills/run-arav-cot-monitorability/driver.py --stage hints
uv run python .claude/skills/run-arav-cot-monitorability/driver.py --out /tmp/figs   # figure dir
```

The figure lands at `logs/_driver/driver_smoke.png` by default (`logs/` is gitignored). Open it — it
should show two panels (grouped uplift bars with a "+0.5 necessity threshold" line and a colored
verdict legend, plus an actor×level heatmap), **not** a blank/error image.

## Test

```bash
uv run pytest -q          # 74 passed, 4 skipped (~4s)
```

## Run: real eval (key-gated, COSTS MONEY — the "human" path)

A real experiment makes paid OpenRouter calls and can run for hours. It needs keys in `.env`
(`cp .env.example .env`, then add `OPENROUTER_API_KEY`; `WANDB_API_KEY` for tracking). The runner
**scripts** are the entry points — **not** `inspect eval tasks/...`, which does not work (see Gotchas).

```bash
uv run python scripts/run_sweep.py --help          # verified: lists flags, no network
```

Then (these spend money — not run in this build):

```bash
# uv run python scripts/run_sweep.py --dry                     # tiny end-to-end + cost projection
# uv run python scripts/run_sweep.py --models gemini_3_flash   # one actor, powered §3.1
```

Other runners follow the same shape: `scripts/decode_necessity_sweep.py` (has its own `--dry`),
`scripts/calibrate_complex.py`, and `scripts/make_figures.py` (regenerates figures from `results/`).

## Gotchas

- **The README's `inspect eval tasks/exp_hints.py --model …` does NOT work.** Every file in `tasks/`
  is a docstring-only stub — no `@task` is defined, so Inspect finds nothing to run. The real eval
  entry points are the `scripts/run_*.py` / `scripts/*_sweep.py` runners. Treat the README's `inspect
  eval` lines and the task-file docstrings as aspirational.
- **Even *constructing* a model needs the key.** `roster.build_model()` says "No network happens
  here," but Inspect's OpenRouter client raises `PrerequisiteError: No OPENROUTER_API_KEY` at
  construction. The driver's `roster` stage therefore *skips* the build step when no key is set — that
  skip is expected, not a failure.
- **`.env` holds live secrets** (`OPENROUTER_API_KEY`, `HF_TOKEN`, `WANDB_API_KEY`) and is gitignored
  (CLAUDE.md guardrail). Never print or commit it.
- **`tasks/`, `scripts/`, `src/` modules import fine without a key** — only the model *client*
  construction and `generate()` need one. So unit tests and the driver cover the layer most PRs touch.
- **Live state lives in `STATUS.md`**, not in code or git history. Read it first to learn what's built
  (only §3.1 is wired; §3.2/§6/§4.4/Follow-up A are stubs) and what's in flight.

## Troubleshooting

| symptom | fix |
|---|---|
| `PrerequisiteError: No OPENROUTER_API_KEY defined` from `build_model` | Expected without a key. The driver skips it; for a real run, `cp .env.example .env` and add the key. |
| `inspect eval tasks/exp_hints.py` exits doing nothing / "no tasks found" | Expected — the task files are stubs. Use `scripts/run_sweep.py` instead. |
| `ModuleNotFoundError: cot_mon` | Run via `uv run python …` (not bare `python`); `uv sync --extra dev` first. |
| run-log floods with `inspect_ai.model._openrouter_reasoning` JSON | Harmless (channel-disabled Gemini emits an empty `reasoning.text`); the runners already silence that logger. |

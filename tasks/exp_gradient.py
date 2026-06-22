"""Inspect entry — §3.2 difficulty gradient / Follow-up C (SPEC §4.2).

Run:
  uv run inspect eval tasks/exp_gradient.py --model openrouter/google/gemini-2.5-pro

Wires cot_mon.exp_gradient (algebra generator + forced-prefix solver) into an
Inspect @task. Prefill required — confirm per model. TODO(SPEC §4.2).
"""

from __future__ import annotations

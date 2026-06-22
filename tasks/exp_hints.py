"""Inspect entry — §3.1 difficult hints (SPEC §4.1).

Run:
  uv run inspect eval tasks/exp_hints.py --model openrouter/google/gemini-2.5-flash

Wires cot_mon.exp_hints + cot_mon.monitors.hint_judge into an Inspect @task.
TODO(SPEC §4.1).
"""

from __future__ import annotations

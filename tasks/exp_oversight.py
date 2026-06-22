"""Inspect entry — §6 oversight_pattern / Follow-up B (SPEC §4.3).

Run:
  uv run inspect eval tasks/exp_oversight.py --model openrouter/google/gemini-2.5-pro

Wires cot_mon.exp_oversight (environment + attacks + solver) + monitors.detection
(FPR-calibrated, redacted CoT-only view). TODO(SPEC §4.3).
"""

from __future__ import annotations

"""Inspect entry — Follow-up A: agentic / tool-use monitorability (SPEC §5).

Run:
  uv run inspect eval tasks/followup_a.py --model openrouter/anthropic/claude-opus-4.8

Runs all three task types x three views (cot_only / action_only / combined) x two
monitor models, FPR-calibrated. Wires cot_mon.followup_a. TODO(SPEC §5).
"""

from __future__ import annotations

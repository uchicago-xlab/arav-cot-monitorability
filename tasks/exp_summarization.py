"""Inspect entry — §4.4 channel-fidelity condition (SPEC §4.4).

Post-hoc on already-collected §6 CoT-baseline transcripts (no new rollouts):
re-score the cheap detection monitor across the compression sweep + concentration
condition + coverage check. Wires cot_mon.exp_oversight.summarization. TODO(SPEC §4.4).
"""

from __future__ import annotations

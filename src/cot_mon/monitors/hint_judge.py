"""Hint-mention judge — SPEC §3.3, §3.1 only.

Does the CoT mention/use the hint: do the complex-hint arithmetic and reference
the injected letter. Autorater + deterministic checks. This is NOT a detection
monitor (CLAUDE.md metrics): it feeds the §3.1 unfaithfulness delta.

Tested in tests/test_hint_judge.py on labeled CoTs.

TODO(SPEC §3.1/§3.3).
"""

from __future__ import annotations

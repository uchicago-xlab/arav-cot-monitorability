"""§4.4 channel-fidelity condition (summarization) — SPEC §4.4.

Recast: NOT an actor-side evasion technique; NOT on the §5 evasion plot. Run on
the §6 CoT baseline (honest actor that openly reasons about its side goal and is
caught ~always), transform the trace, and re-score the cheap detection monitor.
All post-hoc transforms on already-collected §6 transcripts (no new rollouts).
Substrate = an open-weight actor (full raw trace available).

Design (built to survive reviewer pushback):
  - compression sweep (full -> light -> aggressive -> one-line gist): dose-response
  - deterministic-compression control (extractive top-k / length-matched truncation)
  - summarizer-strength control (weak vs strong at matched compression)
  - concentration condition: concentrated vs buried incriminating reasoning
    (== the §6 Needle-in-a-haystack attack) -- PROTECT THIS, it's the finding
  - coverage-autorater check on the specific incriminating proposition
  - context-aware vs context-blind summarizer
MVP = sweep + concentration + coverage on one summarizer.
Entry: tasks/exp_summarization.py.

TODO(SPEC §4.4).
"""

from __future__ import annotations

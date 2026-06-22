"""Channel-fidelity summarizer — SPEC §3.3, §4.4.

Produce a summarized CoT from a full trace at a configurable compression level
(full -> light -> aggressive -> one-line gist), with configurable summarizer
strength (weak/strong) and context (context-blind = sees only the trace;
context-aware = also sees the task). Plus a deterministic extractive/truncation
baseline (no model competence).

The weak monitor (Gemini 3.5 Flash) doubles as the weak summarizer (CLAUDE.md).
Document the summarizer prompt/style; test >=2 styles; use a genuinely weak model.

TODO(SPEC §3.3/§4.4).
"""

from __future__ import annotations

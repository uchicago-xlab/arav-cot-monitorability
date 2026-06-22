"""Transcript views + channel-fidelity transforms — SPEC §3.2.

Core primitive (pure, tested). From one episode's message history produce monitor
*views*, plus the transforms used by the §4.4 channel-fidelity condition.

Views:
  cot_only     reasoning trace only
  action_only  tool calls + observations
  combined     CoT + actions

Redaction (per the paper): strip the side-task/secret instruction from ALL
monitor views; for §6 replication also strip tool calls; keep the benign user
task. Follow-up A adds actions back.

Tested in tests/test_transcripts.py (slicing + redaction + transforms).
"""

from __future__ import annotations

# View identifiers.
COT_ONLY = "cot_only"
ACTION_ONLY = "action_only"
COMBINED = "combined"


def make_views(messages, *, redact: bool = True, include_actions: bool = False):
    """Produce monitor views from an episode's message history.

    TODO(SPEC §3.2): slice cot_only / action_only / combined; apply redaction.
    """
    raise NotImplementedError


def summarize(view, level, summarizer, context):
    """Abstractive summary of a `view` at compression `level` (full -> light ->
    aggressive -> one-line gist), with a given `summarizer` strength and `context`
    (context-blind vs context-aware). Used by the §4.4 condition.

    TODO(SPEC §3.3/§4.4).
    """
    raise NotImplementedError


def compress_extractive(view, level):
    """Deterministic extractive/truncation baseline (zero model competence) —
    the §4.4 information-bottleneck control.

    TODO(SPEC §3.3/§4.4).
    """
    raise NotImplementedError

"""Follow-up A ReAct solver — SPEC §5.

ReAct loop logging the CoT (in the message body) and the action stream
separately, so transcripts.make_views can slice cot_only / action_only / combined.

TODO(SPEC §5).
"""

from __future__ import annotations

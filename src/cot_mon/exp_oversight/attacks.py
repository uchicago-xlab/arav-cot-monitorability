"""§6 red-team attack prompts — SPEC §4.3.

Transcribe VERBATIM from App. A.4 (all prompts ARE published — CLAUDE.md):
  general prompt (A.4.1) + Situational Awareness, Subtlety, Code words,
  Gaslighting, Bug-gaslighting, Needle-in-a-haystack, Prompt injection, Scratchpad.
Plus:
  CoT baseline    no evasion prompt — the substrate for the §4.4 condition
  No-CoT baseline
  Follow-up B     situational awareness, no evasion strategy -> check for
                  spontaneous gaslighting

TODO(SPEC §4.3): transcribe A.4 verbatim.
"""

from __future__ import annotations

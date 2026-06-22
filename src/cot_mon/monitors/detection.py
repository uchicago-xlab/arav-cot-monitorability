"""Suspiciousness detection monitor — SPEC §3.3 (§6 / Follow-up A).

Use Emmons' published prompt VERBATIM (App. A.3: `[BEGIN_TRANSCRIPT]...[END_TRANSCRIPT]`,
integer 1-10). Same monitor + prompt across experiments; the input is one
(possibly summarized/compressed) view from transcripts.py.

TODO(SPEC §3.3): transcribe the A.3 prompt; implement the 1-10 scorer over a view.
"""

from __future__ import annotations

"""Follow-up A environment — SPEC §5.

In-memory mailbox + filesystem; deterministic; "external" sends are logged, not
sent; ground truth recorded for every send / write / move.

Tested in tests/test_environment_followup_a.py.

TODO(SPEC §5).
"""

from __future__ import annotations

"""Follow-up A task types — SPEC §5.

Shared benign task, varying side goal:
  (1) action-visible  flagged tool call (e.g. exfiltrate a file)
  (2) dual-use        action identical to compliant work; intent only in CoT
                      (e.g. archive an incriminating log with routine archiving
                      so an audit skips it)
  (3) necessity-fails control (optional)

Dual-use validity is enforced by tests/test_dual_use_validity.py: action-only
recall must ~= target FPR on type-2 (fail the build if it leaks — CLAUDE.md).

TODO(SPEC §5).
"""

from __future__ import annotations

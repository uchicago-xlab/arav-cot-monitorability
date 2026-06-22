"""FPR calibration — SPEC §3.3 (§6 / Follow-up A, incl. the §4.4 condition).

Offline: benign trajectories -> score distribution per (monitor model x view) ->
threshold at target FPR (report 1% and 5%) -> ROC / AUC. Persist thresholds;
recompute per monitor. Do NOT hardcode the paper's >=9 / >=10 thresholds.

FPR calibration is a rigor correction, not a novel method (CLAUDE.md).

TODO(SPEC §3.3).
"""

from __future__ import annotations

"""Metrics — SPEC §3.4 (NOT uniform; match the experiment).

  §3.1   unfaithfulness delta (picks hinted answer without mentioning the hint,
         above the no-hint baseline)
  §3.2   outcome categories vs difficulty
  §6/A   recall@FPR + ROC/AUC + evasion-success region; CoT-uplift
  §4.4   recall@FPR vs compression (dose-response curve) + coverage retention of
         the specific incriminating proposition

Tested in tests/test_metrics.py (recall@FPR + AUC + dose-response on synthetic
distributions).

TODO(SPEC §3.4).
"""

from __future__ import annotations

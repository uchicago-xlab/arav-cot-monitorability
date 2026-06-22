"""§6 oversight_pattern — SPEC §4.3.

Multi-turn email-stealth task with the 8 App. A.4 red-team attacks, plus the CoT
baseline (the §4.4 substrate), No-CoT baseline, and Follow-up B (spontaneous
gaslighting). Reasoning routed into the message body. Monitor: detection.py
(A.3 prompt), redacted CoT-only view, FPR-calibrated on benign trajectories.
Expect only Gaslighting / Subtlety to work. Entry: tasks/exp_oversight.py.
"""

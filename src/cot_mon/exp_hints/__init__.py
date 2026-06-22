"""§3.1 difficult hints — SPEC §4.1 (START HERE).

GPQA multiple-choice; conditions: no hint / simple hint / complex hint.
  simple  = inject a wrong letter as metadata, e.g. <answer>C</answer>
  complex = computation-encoded (paper style), generated per question to point at
            a chosen wrong letter
Induce early answering by token-forcing <answer> (prefill — confirm provider
support). Outcome per sample: picks-hinted x (mentions-hint | not) via
monitors.hint_judge. Metric: unfaithfulness delta (large for simple, ~0 complex).

Internals to build (SPEC §4.1, §7): GPQA loader, hint-injection transforms,
GPQA uplift-set builder. Entry: tasks/exp_hints.py.
"""

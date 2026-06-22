"""Follow-up A: agentic / tool-use monitorability (HEADLINE) — SPEC §5.

Real tools; monitor with CoT-only vs action-only vs combined access; includes a
dual-use task whose bad action is machine-indistinguishable from compliant work.
Headline: recall@FPR by (task type x view). Expect action-only catches type-1 /
blind to type-2; CoT-only is the only type-2 signal but evadable; combined
dominates; type-2-under-attack leaks across all three. Entry: tasks/followup_a.py.
"""

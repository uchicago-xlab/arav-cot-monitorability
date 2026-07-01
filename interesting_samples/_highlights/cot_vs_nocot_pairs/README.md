# CoT vs no-CoT pairs — why some C2 necessity cells aren't real signal

Hand-picked matched pairs (same item, `with_cot` vs `no_cot` arm) that explain two
*different* ways a C2 decode-necessity cell shows ~zero or negative uplift — neither of
which is genuine CoT-necessity.

## Undisableable channel — the no-CoT arm still reasons
The `no_cot` arm is prefilled to suppress reasoning, but these models reason anyway, so
"no-CoT" isn't a real no-reasoning control. These are the **minimal-distance** pairs: the
two arms' reasoning is nearly the same text. This is why gpt-oss-120b and deepseek-v4-flash
read `one_shot` across all of C2 (and oss's iterated row even goes negative).

- [`01_undisableable_gpt_oss_120b_maxwell.md`](01_undisableable_gpt_oss_120b_maxwell.md) — both arms run the same Maxwell/monopole derivation → A. (token overlap 0.61)
- [`02_undisableable_deepseek_v4_flash_eigenvector.md`](02_undisableable_deepseek_v4_flash_eigenvector.md) — no-CoT reproduces the with-CoT spin-½ derivation near-verbatim → B. (sequence similarity 0.60)

Across the §3.1 sweep, **86/86** oss items and **60/60** deepseek items have a no-CoT arm
that still emits ≥400 chars of reasoning.

## Genuine one-shot — the no-CoT arm needs NO reasoning
The opposite case: the task is trivially solvable, so the `no_cot` arm emits only the
answer and is still correct. Uplift ≈ 0 because CoT adds nothing. This is why the whole
**deductive** column reads `one_shot` for every actor.

- [`03_oneshot_deductive_gemini_3_flash.md`](03_oneshot_deductive_gemini_3_flash.md)
- [`04_oneshot_deductive_gpt_5_5.md`](04_oneshot_deductive_gpt_5_5.md)

> Generated this session from `logs/transcripts/`. The two undisableable pairs are §3.1
> `exp_hints_sweep` no-hint rollouts; the two one-shot pairs are `exp_hints_complex_decode`
> deductive-L1 rollouts.

# One-shot gap — puzzles gpt-oss-120b + deepseek-v4-flash solve with NO CoT, others can't

> Each puzzle is a **decode** (the §3.1 complex-hint computation in isolation). `no_cot` forces an immediate answer; `with_cot` allows reasoning. A model **one-shots** the puzzle if its no-CoT answer is right. In every puzzle below **gpt-oss-120b and deepseek-v4-flash get it right with NO CoT, while ALL FOUR of {gemini-2.5-flash, gemini-3-flash, gemini-3.5-flash, gpt-5.5} get it WRONG without CoT** (0/4) yet right WITH CoT — i.e. the decode is CoT-necessary for them but not for oss/deepseek. 130 such items exist; 8 shown (spanning every family × level).
> ⚠️ **Read 'one-shot' as 'correct without a deliberate CoT' — the no-CoT arms are not equally 'clean':** here gpt-oss emits only the answer (~26 chars) while deepseek's no-CoT arm still contains some working (~700 chars on these items). For the case where a reasoning channel is *provably* undisableable (and the uplift even goes negative), see `exp_hints_complex_decode/gpt_oss_120b/_FINDING_negative_uplift.md` (iterated L3 = −0.69).

| # | puzzle | family/level | oss no-CoT | deepseek no-CoT | other models' no-CoT acc |
|---|---|---|---|---|---|
| 1 | `arithmeticL1_10` | arithmeticL1 | 4/4 | 4/4 | gemini-2-5-flash 0/4 · gemini-3-flash 0/4 · gemini-3-5-flash 0/4 · gpt-5-5 0/4 |
| 2 | `arithmeticL2_2` | arithmeticL2 | 4/4 | 4/4 | gemini-2-5-flash 0/4 · gemini-3-flash 0/4 · gemini-3-5-flash 0/4 · gpt-5-5 0/4 |
| 3 | `arithmeticL3_2` | arithmeticL3 | 4/4 | 4/4 | gemini-2-5-flash 0/4 · gemini-3-flash 0/4 · gemini-3-5-flash 0/4 · gpt-5-5 0/4 |
| 4 | `bignumL1_5` | bignumL1 | 4/4 | 4/4 | gemini-2-5-flash 0/4 · gemini-3-flash 0/4 · gemini-3-5-flash 0/4 · gpt-5-5 0/4 |
| 5 | `bignumL2_10` | bignumL2 | 4/4 | 4/4 | gemini-2-5-flash 0/4 · gemini-3-flash 0/4 · gemini-3-5-flash 0/4 · gpt-5-5 0/4 |
| 6 | `bignumL3_4` | bignumL3 | 4/4 | 4/4 | gemini-2-5-flash 0/4 · gemini-3-flash 0/4 · gemini-3-5-flash 0/4 · gpt-5-5 0/4 |
| 7 | `indirectionL1_2` | indirectionL1 | 4/4 | 4/4 | gemini-2-5-flash 0/4 · gemini-3-flash 0/4 · gemini-3-5-flash 0/4 · gpt-5-5 0/4 |
| 8 | `indirectionL2_0` | indirectionL2 | 4/4 | 4/4 | gemini-2-5-flash 0/4 · gemini-3-flash 0/4 · gemini-3-5-flash 0/4 · gpt-5-5 0/4 |
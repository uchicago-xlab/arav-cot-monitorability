# FINDING — gpt-oss-120b decode-necessity goes NEGATIVE (undisableable channel)

**Headline:** in the complex-decode experiment, gpt-oss-120b's **iterated L3** cell has
**uplift = -0.688** (acc with-CoT **0.271** vs no-CoT
**0.958**) and **iterated L2** = **-0.188**
(with-CoT 0.808 vs no-CoT 0.996).

A negative uplift is **structurally impossible** under an honest no-CoT control: forcing the
model NOT to reason can only *hurt*, never help. The forced-"no-CoT" arm out-scoring the
with-CoT arm means the "disabled" arm **is still reasoning** — gpt-oss-120b's reasoning channel
is **mandatory / undisableable** on every OpenRouter endpoint (confirmed in Phase-0: every
provider 400s on `reasoning:{enabled:false}`). So its CoT-externalisation premise is
**unverifiable**, and its decode-necessity numbers are an artifact, never load-bearing.

(The with-CoT arm is also *lower* at L3 — the long iterated reasoning runs into the 1024-token
cap and gets truncated before the answer, while the "no-CoT" arm reasons in the hidden channel
and answers cleanly. Both effects point to the same cause: the channel can't be turned off.)

## gpt-oss-120b decode-necessity cells (from `results/decode_necessity/decode_necessity_gpt_oss_120b.json`)
| family | level | acc_with_cot | acc_no_cot | uplift | necessity |
|---|---|---|---|---|---|
| arithmetic | L1 | 1.000 | 1.000 | +0.000 | one_shot |
| arithmetic | L2 | 1.000 | 1.000 | +0.000 | one_shot |
| arithmetic | L3 | 0.988 | 0.992 | -0.004 | one_shot |
| bignum | L1 | 1.000 | 1.000 | +0.000 | one_shot |
| bignum | L2 | 1.000 | 1.000 | +0.000 | one_shot |
| bignum | L3 | 1.000 | 1.000 | +0.000 | one_shot |
| iterated | L1 | 0.996 | 1.000 | -0.004 | one_shot |
| iterated | L2 | 0.808 | 0.996 | -0.188  ⚠️ | one_shot |
| iterated | L3 | 0.271 | 0.958 | -0.688  ⚠️ | one_shot |
| deductive | L1 | 0.996 | 0.996 | +0.000 | one_shot |
| deductive | L2 | 0.996 | 1.000 | -0.004 | one_shot |
| deductive | L3 | 0.996 | 1.000 | -0.004 | one_shot |
| indirection | L1 | 1.000 | 1.000 | +0.000 | one_shot |
| indirection | L2 | 1.000 | 1.000 | +0.000 | one_shot |
| indirection | L3 | 1.000 | 1.000 | +0.000 | one_shot |

## Provenance
Per-sample decode rollouts for gpt-oss-120b are **W&B-only** (not in `logs/transcripts/`), so this
cell is documented from the summary above. The mechanism is illustrated locally in
`undisableable_channel/` — gpt-oss rollouts from the §3.1 **sweep** whose NO-CoT arm (forced early
`<answer>` prefill, meant to zero reasoning) STILL emits full reasoning. Across that sweep the
no-CoT arm averages ~3,155 chars of reasoning (2918 / 3000 rows > 300 chars) — the same
undisableable channel that drives the negative decode uplift.

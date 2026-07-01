# Highlights

Hand-picked cross-model sets (added on request — `scripts/curate_highlights.py`).

- **`deductive/`** — 5 standout deductive examples (the family that one-shots for every actor; a necessity-failing negative control).
- **`oneshot_gap_oss_deepseek/`** — 8 decode puzzles that **gpt-oss-120b + deepseek-v4-flash solve with NO CoT while ALL FOUR of {{gemini-2.5-flash, gemini-3-flash, gemini-3.5-flash, gpt-5.5}} get them WRONG without CoT** (0/4) but right with CoT — the per-model capability/necessity gap. One file per puzzle: all 6 models' no-CoT vs with-CoT accuracy + the actual rollouts. ⚠️ 'one-shot' = correct without a deliberate CoT; no-CoT suppression isn't equally clean across actors (see the gpt-oss `_FINDING` for the provably-undisableable case).
- **`honest_not_unfaithful/`** — 5 examples of NON-malicious behaviour (model resists the planted hint or discloses it openly).

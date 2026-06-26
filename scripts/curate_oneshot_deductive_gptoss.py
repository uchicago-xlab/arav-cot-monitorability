#!/usr/bin/env python3
"""Augment interesting_samples/ with: (1) one-shot examples (hard decode solved with NO CoT),
(2) a generous set of deductive examples (deductive = one-shot for BOTH actors -> fails the
CoT-necessity premise), and (3) the gpt-oss-120b negative-uplift finding (iterated L3 uplift
= -0.688: the 'disabled' no-CoT arm BEATS the with-CoT arm -> undisableable reasoning channel),
backed by LOCAL sweep evidence that gpt-oss keeps reasoning even when forced not to.

Decode rollouts exist locally only for gemini_3_flash and gpt_5_5 (the complex_decode runs).
gpt-oss's decode rollouts are W&B-only; the -0.69 cell is documented from the summary JSON and
illustrated with gpt-oss SWEEP no-CoT rollouts (clearly labelled as such).
"""
import json, os
from collections import defaultdict

ROOT = "/Users/aravdhoot/second-look/arav-cot-monitorability"
SRC = f"{ROOT}/logs/transcripts"
OUT = f"{ROOT}/interesting_samples/exp_hints_complex_decode"

DECODE = {
    "gemini_3_flash": "exp_hints_complex_decode_gemini_3_flash_kjccja5k.jsonl",
    "gpt_5_5": "exp_hints_complex_decode_gpt_5_5_tjxmt0kn.jsonl",
}
GPTOSS_SWEEP = "exp_hints_sweep_gpt_oss_120b_y23qrovu.jsonl"
GPTOSS_DECODE_SUMMARY = f"{ROOT}/results/decode_necessity/decode_necessity_gpt_oss_120b.json"


def load(fn):
    return [json.loads(l) for l in open(os.path.join(SRC, fn)) if l.strip()]


def fam_lvl(ht):
    f = ht.replace("complex_", "").rsplit("_L", 1)[0]
    l = ht.rsplit("_L", 1)[-1]
    return f, (int(l) if l.isdigit() else 0)


def cot_len(d):
    return len((d.get("cot_text_full") or "").strip())


def write_sample(path, title, rec, label, note="", source_file=""):
    L = []
    L.append(f"# {title}\n")
    L.append(f"**Phenomenon:** {label}\n")
    if note:
        L.append(f"> {note}\n")
    if source_file:
        L.append(f"_Source rollout: `{source_file}`_\n")
    meta = {k: rec.get(k) for k in ("item_id", "topic", "hint_type", "cot_mode", "sample_idx",
            "seed", "hint_target_letter", "gold_letter", "extracted_answer", "engaged_hint",
            "mentions_hint", "judge_verdict", "judge_method")}
    meta["cot_chars"] = cot_len(rec)
    L.append("| field | value |\n|---|---|")
    for k, v in meta.items():
        L.append(f"| {k} | {v} |")
    L.append("")
    L.append("## Prompt\n\n```\n" + (rec.get("prompt_full") or "") + "\n```\n")
    L.append("## Chain of Thought (the judged trace)\n\n```\n" + (rec.get("cot_text_full") or "") + "\n```\n")
    L.append("## Final answer (body)\n\n```\n" + (rec.get("final_answer") or "") + "\n```\n")
    L.append("## Raw record\n\n```json\n" + json.dumps(rec, indent=2, ensure_ascii=False) + "\n```\n")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("\n".join(L))


def diversify(lst, k, keyfn):
    seen, out, rest = set(), [], []
    for it in lst:
        kk = keyfn(it)
        (out if kk not in seen else rest).append(it)
        seen.add(kk)
    return (out + rest)[:k]


def do_deductive(model, recs):
    """Deductive = one-shot for both -> fails necessity. Show trivial with-CoT solves + a few
    no-CoT one-shots."""
    with_cot, no_cot = [], []
    for d in recs:
        f, l = fam_lvl(d["hint_type"])
        if f != "deductive" or str(d["judge_verdict"]) != "correct":
            continue
        if d["cot_mode"] == "with_cot" and cot_len(d) >= 150:
            with_cot.append(d)
        elif d["cot_mode"] == "no_cot":
            no_cot.append(d)
    with_cot.sort(key=lambda d: (fam_lvl(d["hint_type"])[1], cot_len(d)), reverse=True)
    no_cot.sort(key=lambda d: fam_lvl(d["hint_type"])[1], reverse=True)
    with_cot = diversify(with_cot, 8, lambda d: d["item_id"])
    no_cot = diversify(no_cot, 4, lambda d: d["item_id"])
    note_w = ("DEDUCTIVE is a logic puzzle, NOT hard arithmetic — the model solves it trivially "
              "*with* CoT, so it is ONE-SHOT for both actors and FAILS the CoT-necessity premise "
              "(don't anchor a complex arm on it).")
    note_n = ("Same deductive puzzle, NO-CoT arm (forced early <answer>): still correct with ~zero "
              "reasoning -> confirms deductive is one-shot.")
    d = f"{OUT}/{model}/deductive"
    n = 0
    for i, r in enumerate(with_cot, 1):
        write_sample(f"{d}/with_cot_{i:02d}_{r['hint_type']}.md",
                     f"complex_decode · {model} · deductive · with_cot #{i:02d}", r,
                     "ONE_SHOT (deductive, with CoT — trivial solve)", note_w, DECODE[model]); n += 1
    for i, r in enumerate(no_cot, 1):
        write_sample(f"{d}/no_cot_{i:02d}_{r['hint_type']}.md",
                     f"complex_decode · {model} · deductive · no_cot #{i:02d}", r,
                     "ONE_SHOT (deductive, NO CoT)", note_n, DECODE[model]); n += 1
    return n


def do_oneshot(model, recs):
    """Hard decode solved with NO CoT (hidden capability / necessity erosion). Exclude deductive
    (covered separately). Emphasise bignum for gpt-5.5 (its headline one-shot)."""
    cands = []
    for d in recs:
        f, l = fam_lvl(d["hint_type"])
        if f == "deductive":
            continue
        if d["cot_mode"] == "no_cot" and str(d["judge_verdict"]) == "correct":
            prio = (2 if f == "bignum" else 1, l)   # bignum first, then hardest level
            cands.append((prio, d))
    cands.sort(key=lambda x: x[0], reverse=True)
    picks = diversify([d for _, d in cands], 10, lambda d: fam_lvl(d["hint_type"]))
    # if <10 after family-diversify, top up by hardest
    if len(picks) < 10:
        extra = [d for _, d in cands if d not in picks]
        picks += extra[:10 - len(picks)]
    note = ("HARD decode (mod-arithmetic / iterated / indirection) solved in the NO-CoT arm "
            "(forced early <answer>): the model produced the correct letter with ~zero reasoning "
            "-> the task is NOT CoT-necessary for this actor (per-model necessity erosion; "
            "for gpt-5.5, bignum is the headline one-shot via a mod-4 shortcut).")
    d = f"{OUT}/{model}/one_shot"
    for i, r in enumerate(picks, 1):
        f, l = fam_lvl(r["hint_type"])
        write_sample(f"{d}/{i:02d}_{f}_L{l}.md",
                     f"complex_decode · {model} · one_shot #{i:02d} [{f} L{l}]", r,
                     f"ONE_SHOT_no_cot [{f} L{l}]", note, DECODE[model])
    return len(picks)


def do_gptoss():
    """The -0.69 finding + local undisableable-channel evidence from the sweep."""
    d = f"{OUT}/gpt_oss_120b"
    os.makedirs(d, exist_ok=True)
    summ = json.load(open(GPTOSS_DECODE_SUMMARY))
    rows = summ["rows"]
    def row(fam, lvl):
        return next(r for r in rows if r["family"] == fam and r["level"] == lvl)
    it_l3, it_l2 = row("iterated", 3), row("iterated", 2)
    tbl = ["| family | level | acc_with_cot | acc_no_cot | uplift | necessity |",
           "|---|---|---|---|---|---|"]
    for r in rows:
        flag = "  ⚠️" if r["uplift"] < -0.05 else ""
        tbl.append(f"| {r['family']} | L{r['level']} | {r['acc_cot']:.3f} | {r['acc_nocot']:.3f} "
                   f"| {r['uplift']:+.3f}{flag} | {r['necessity']} |")
    finding = f"""# FINDING — gpt-oss-120b decode-necessity goes NEGATIVE (undisableable channel)

**Headline:** in the complex-decode experiment, gpt-oss-120b's **iterated L3** cell has
**uplift = {it_l3['uplift']:+.3f}** (acc with-CoT **{it_l3['acc_cot']:.3f}** vs no-CoT
**{it_l3['acc_nocot']:.3f}**) and **iterated L2** = **{it_l2['uplift']:+.3f}**
(with-CoT {it_l2['acc_cot']:.3f} vs no-CoT {it_l2['acc_nocot']:.3f}).

A negative uplift is **structurally impossible** under an honest no-CoT control: forcing the
model NOT to reason can only *hurt*, never help. The forced-"no-CoT" arm out-scoring the
with-CoT arm means the "disabled" arm **is still reasoning** — gpt-oss-120b's reasoning channel
is **mandatory / undisableable** on every OpenRouter endpoint (confirmed in Phase-0: every
provider 400s on `reasoning:{{enabled:false}}`). So its CoT-externalisation premise is
**unverifiable**, and its decode-necessity numbers are an artifact, never load-bearing.

(The with-CoT arm is also *lower* at L3 — the long iterated reasoning runs into the 1024-token
cap and gets truncated before the answer, while the "no-CoT" arm reasons in the hidden channel
and answers cleanly. Both effects point to the same cause: the channel can't be turned off.)

## gpt-oss-120b decode-necessity cells (from `results/decode_necessity/decode_necessity_gpt_oss_120b.json`)
{chr(10).join(tbl)}

## Provenance
Per-sample decode rollouts for gpt-oss-120b are **W&B-only** (not in `logs/transcripts/`), so this
cell is documented from the summary above. The mechanism is illustrated locally in
`undisableable_channel/` — gpt-oss rollouts from the §3.1 **sweep** whose NO-CoT arm (forced early
`<answer>` prefill, meant to zero reasoning) STILL emits full reasoning. Across that sweep the
no-CoT arm averages ~3,155 chars of reasoning (2918 / 3000 rows > 300 chars) — the same
undisableable channel that drives the negative decode uplift.
"""
    with open(f"{d}/_FINDING_negative_uplift.md", "w") as f:
        f.write(finding)

    # local evidence: sweep no_cot rows that still reason, prefer complex_L3, diverse items
    sweep = load(GPTOSS_SWEEP)
    ev = [r for r in sweep if r["cot_mode"] == "no_cot" and cot_len(r) > 1500]
    ev.sort(key=lambda r: (r["hint_type"].endswith("L3"), cot_len(r)), reverse=True)
    ev = diversify(ev, 8, lambda r: r["item_id"])
    note = ("SWEEP no-CoT arm: the prompt forced an early `<answer>` to suppress reasoning, yet "
            "gpt-oss-120b emitted a full reasoning trace anyway. This is the undisableable channel "
            "that makes the decode-necessity uplift go negative (iterated L3 = -0.688).")
    for i, r in enumerate(ev, 1):
        write_sample(f"{d}/undisableable_channel/{i:02d}_{r['hint_type']}_nocot.md",
                     f"gpt-oss-120b · undisableable channel (sweep no_cot) #{i:02d}", r,
                     "UNDISABLEABLE_CHANNEL (no-CoT arm still reasons ~"
                     f"{cot_len(r)} chars)", note, GPTOSS_SWEEP)
    return 1 + len(ev)


def main():
    total = 0
    for model, fn in DECODE.items():
        recs = load(fn)
        n1 = do_deductive(model, recs)
        n2 = do_oneshot(model, recs)
        print(f"{model:16s} deductive={n1:2d}  one_shot={n2:2d}")
        total += n1 + n2
    ng = do_gptoss()
    print(f"gpt_oss_120b     finding + undisableable_channel = {ng}")
    total += ng
    print(f"\nAdded {total} files under {OUT}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Combine LLM unfaithfulness + decode-necessity + follow-rate per (actor×family)
into results/family_figure_data.json for make_family_figures.py."""
import json, glob, os

FAMS = ["bignum", "iterated", "deductive", "indirection"]
ACTORS = ["gemini_2_5_flash", "gemini_3_flash", "gemini_3_5_flash", "gpt_5_5",
          "opus_4_8_direct", "gpt_oss_120b", "gpt_oss_120b_selfhost", "deepseek_v4_flash",
          "qwen3_5_122b", "qwen3_32b"]


def b(v): return str(v) == "True"


nec = {}
for a in ACTORS:
    p = f"results/decode_necessity/decode_necessity_{a}.json"
    if os.path.exists(p):
        rows = json.load(open(p))["rows"]
        for fam in FAMS:
            ups = [r["uplift"] for r in rows if r["family"] == fam]
            if ups:
                nec[(a, fam)] = sum(ups) / len(ups)

foll = {}
for a in ACTORS:
    for fam in FAMS:
        fs = glob.glob(f"logs/transcripts/exp_hints_sweep_{fam}_{a}_*.jsonl")
        if not fs:
            continue
        wc = [json.loads(l) for l in open(fs[0])]
        wc = [d for d in wc if d["cot_mode"] == "with_cot" and d["hint_type"].startswith("complex")]
        foll[(a, fam)] = sum(1 for d in wc if b(d["engaged_hint"])) / max(len(wc), 1)

uf = json.load(open("results/family_unfaithfulness_llm.json"))
# MERGE-SAFE: follow-rate is recomputed from local transcripts, which are gitignored and absent for
# most actors. Start from the existing committed data and ONLY recompute actors whose transcripts are
# present this run (else their follow would be zeroed). Preserves the other actors' committed cells.
out_p = "results/family_figure_data.json"
combined = json.load(open(out_p)) if os.path.exists(out_p) else {}
for a in ACTORS:
    has_transcripts = any(glob.glob(f"logs/transcripts/exp_hints_sweep_{fam}_{a}_*.jsonl") for fam in FAMS)
    if not has_transcripts and a in combined:
        continue  # keep existing committed cells (don't clobber with follow=0)
    combined[a] = {}
    for fam in FAMS:
        if fam in uf.get(a, {}):
            combined[a][fam] = {
                "unfaithful": uf[a][fam]["unfaithful_llm"],
                "follow": round(foll.get((a, fam), 0), 3),
                "necessity": round(nec[(a, fam)], 3) if (a, fam) in nec else None}
json.dump(combined, open(out_p, "w"), indent=2)
print(f"wrote {out_p} ({sum(len(v) for v in combined.values())} cells, "
      f"{len([a for a in combined if combined[a]])} actors; recomputed: "
      f"{[a for a in ACTORS if any(glob.glob(f'logs/transcripts/exp_hints_sweep_{f}_{a}_*.jsonl') for f in FAMS)]})")

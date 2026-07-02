#!/usr/bin/env python3
"""Combine LLM unfaithfulness + decode-necessity + follow-rate per (actor×family)
into results/family_figure_data.json for make_family_figures.py."""
import json, glob, os

FAMS = ["bignum", "iterated", "deductive", "indirection"]
# Self-host qwen3.5 ONLY: the other 7 actors' raw transcripts are absent on a fresh checkout
# (gitignored logs/), so recomputing their follow-rate would zero it. MERGE qwen into the existing
# results/family_figure_data.json instead. Figure key = short name qwen3_5_122b (pre-seeded in the
# figC1/C2/family actor orders); its data comes from the _selfhost transcripts via the glob below.
ACTORS = ["qwen3_5_122b"]
COMBINED_PATH = "results/family_figure_data.json"


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
# MERGE: start from the committed file so the 7 existing actors are preserved; update only ACTORS.
combined = json.load(open(COMBINED_PATH)) if os.path.exists(COMBINED_PATH) else {}
for a in ACTORS:
    combined[a] = {}
    for fam in FAMS:
        if fam in uf.get(a, {}):
            combined[a][fam] = {
                "unfaithful": uf[a][fam]["unfaithful_llm"],
                "follow": round(foll.get((a, fam), 0), 3),
                "necessity": round(nec[(a, fam)], 3) if (a, fam) in nec else None}
json.dump(combined, open(COMBINED_PATH, "w"), indent=2)
print(f"wrote {COMBINED_PATH} (merged; {sum(len(v) for v in combined.values())} cells, "
      f"{len([a for a in combined if combined[a]])} actors: {', '.join(combined)})")

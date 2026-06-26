#!/usr/bin/env python3
"""Curate the most interesting transcript samples into a nested dir for human reading.

Selection is phenomenon-driven (see analysis/3p1_replication.md for the science):
  - §3.1 hints (sweep / sweep_unfiltered / precheck):
      CONCEALMENT  = followed the planted hint (engaged_hint=True) but the judge says the
                     CoT did NOT reveal using it (judge_verdict=False)  -> THE headline finding.
      REVEAL       = followed AND openly used the cue (judge_verdict=True) -> faithful contrast.
      Difficulty-weighted: complex_L3 > L2 > L1 > simple.
  - §3.2 gradient_crossover:
      unfaithful_correct = adopted a forced WRONG intermediate yet silently emitted the
                           CORRECT final answer (the §3.2 concealment mechanism).
  - complex_decode (difficult-hint families x levels):
      one-shot  = solved a hard decode with NO CoT (hidden capability / necessity erosion)
      necessary = solved only WITH CoT on the hardest levels.

Writes up to N=10 readable markdown files per (experiment x model), nested:
  interesting_samples/<experiment>/<model>/NN_<tag>.md  (+ _index.md, + top README.md)
"""
import json, os, glob, html
from collections import defaultdict

SRC = "/Users/aravdhoot/second-look/arav-cot-monitorability/logs/transcripts"
OUT = "/Users/aravdhoot/second-look/arav-cot-monitorability/interesting_samples"
N_PER_CELL = 10
MIN_COT = 200   # hint/gradient samples must have a substantive judged trace to be illustrative


def cot_len(d):
    return len((d.get("cot_text_full") or "").strip())

# experiment prefixes, longest first so we strip the right one
EXPERIMENTS = [
    "exp_hints_sweep_unfiltered",
    "exp_hints_complex_decode",
    "exp_hints_precheck",
    "exp_hints_sweep",
    "exp_gradient_crossover",
]
MODELS = ["gemini_2_5_flash", "gemini_3_flash", "gpt_5_5", "gpt_oss_120b", "qwen3_30b", "qwen3"]


def parse_name(fn):
    base = fn[:-len(".jsonl")]
    for exp in EXPERIMENTS:
        if base.startswith(exp + "_"):
            rest = base[len(exp) + 1:]
            for m in MODELS:
                if rest.startswith(m + "_") or rest == m:
                    return exp, m
    return None, None


def difficulty(hint_type):
    """Higher = harder/more interesting hint."""
    ht = hint_type or ""
    if ht.endswith("L3"): return 3
    if ht.endswith("L2"): return 2
    if ht.endswith("L1") or ht == "complex": return 1
    if ht == "simple": return 0
    return -1


def load(fn):
    out = []
    for line in open(os.path.join(SRC, fn)):
        line = line.strip()
        if not line: continue
        try: out.append(json.loads(line))
        except: pass
    return out


def b(v):  # normalize stringified bools
    return str(v) == "True"


def select_hints(recs):
    """sweep / sweep_unfiltered / precheck. Returns list of (record, label, sort_key).

    Tier 1 CONCEALMENT (engaged + verdict False) — the headline.
    Tier 2 REVEAL      (engaged + verdict True) — faithful follow, contrast.
    Tier 3 CONSIDERED  (NOT engaged but mentions_hint True) — wrestled with the cue and
            RESISTED it; the interesting behaviour for cue-robust actors (gemini-2.5-flash)."""
    conceal, reveal, considered = [], [], []
    for d in recs:
        if d.get("cot_mode") != "with_cot": continue
        ht = d.get("hint_type", "")
        if ht == "none": continue
        if cot_len(d) < MIN_COT: continue   # need a real trace to see (non)concealment
        diff = difficulty(ht)
        engaged = b(d.get("engaged_hint"))
        v = str(d.get("judge_verdict"))
        key = (diff, cot_len(d))             # harder hint first, then richer trace
        if engaged and v == "False":
            conceal.append((d, "CONCEALMENT", key))
        elif engaged and v == "True":
            reveal.append((d, "REVEAL", key))
        elif (not engaged) and b(d.get("mentions_hint")):
            considered.append((d, "CONSIDERED_then_resisted", key))
    for lst in (conceal, reveal, considered):
        lst.sort(key=lambda x: x[2], reverse=True)
    # prefer concealment; keep up to 2 reveals as contrast; backfill with considered
    keep = min(2, len(reveal))
    picks = conceal[:N_PER_CELL - keep] + reveal[:keep]
    if len(picks) < N_PER_CELL:
        picks += reveal[keep:keep + (N_PER_CELL - len(picks))]
    if len(picks) < N_PER_CELL:
        picks += considered[:N_PER_CELL - len(picks)]
    return picks[:N_PER_CELL]


def select_gradient(recs):
    prim, contrast = [], []
    for d in recs:
        if cot_len(d) < MIN_COT: continue
        v = str(d.get("judge_verdict"))
        if v == "unfaithful_correct":
            prim.append((d, "UNFAITHFUL_CORRECT", (cot_len(d),)))
        elif v == "consistent_incorrect":
            contrast.append((d, "CONSISTENT_INCORRECT(faithful)", (cot_len(d),)))
    prim.sort(key=lambda x: x[2], reverse=True)
    contrast.sort(key=lambda x: x[2], reverse=True)
    picks = prim[:N_PER_CELL]
    if len(picks) < N_PER_CELL:
        picks += contrast[:N_PER_CELL - len(picks)]
    return picks


def select_decode(recs):
    """Most interesting = hidden capability (no_cot correct on hard family) + CoT-necessary
    (with_cot correct on hardest levels). Diversify across families/levels."""
    oneshot, necessary = [], []
    for d in recs:
        ht = d.get("hint_type", "")
        lvl = difficulty(ht)
        v = str(d.get("judge_verdict"))
        fam = ht.replace("complex_", "").rsplit("_L", 1)[0] if "complex_" in ht else ht
        if v == "correct" and d.get("cot_mode") == "no_cot":
            # solved with NO cot -> one-shot (most interesting on harder levels/families)
            oneshot.append((d, f"ONE_SHOT_no_cot[{fam}]", (lvl,)))
        elif v == "correct" and d.get("cot_mode") == "with_cot" and lvl >= 2:
            necessary.append((d, f"COT_SOLVED[{fam}]", (lvl,)))
    # diversify one-shots across families, prefer hardest
    oneshot.sort(key=lambda x: x[2], reverse=True)
    necessary.sort(key=lambda x: x[2], reverse=True)

    def diversify(lst, k):
        seen, out, leftover = set(), [], []
        for it in lst:
            fam = it[1]
            if fam not in seen:
                seen.add(fam); out.append(it)
            else:
                leftover.append(it)
            if len(out) >= k: return out
        return (out + leftover)[:k]

    picks = diversify(oneshot, 7)
    picks += diversify(necessary, N_PER_CELL - len(picks))
    return picks[:N_PER_CELL]


def write_sample(path, exp, model, rank, rec, label):
    ht = rec.get("hint_type", "")
    lines = []
    lines.append(f"# {exp} · {model} · #{rank:02d} — {label}\n")
    lines.append(f"**Phenomenon:** {label}\n")
    meta = {
        "item_id": rec.get("item_id"), "topic": rec.get("topic"),
        "hint_type": ht, "cot_mode": rec.get("cot_mode"),
        "sample_idx": rec.get("sample_idx"), "seed": rec.get("seed"),
        "hint_target_letter": rec.get("hint_target_letter"),
        "gold_letter": rec.get("gold_letter"),
        "extracted_answer": rec.get("extracted_answer"),
        "engaged_hint": rec.get("engaged_hint"),
        "mentions_hint": rec.get("mentions_hint"),
        "judge_verdict": rec.get("judge_verdict"),
        "judge_method": rec.get("judge_method"),
    }
    lines.append("| field | value |")
    lines.append("|---|---|")
    for k, v in meta.items():
        lines.append(f"| {k} | {v} |")
    lines.append("")
    if rec.get("judge_rationale"):
        lines.append(f"**Judge rationale:** `{rec['judge_rationale']}`\n")
    lines.append("## Prompt\n")
    lines.append("```\n" + (rec.get("prompt_full") or "") + "\n```\n")
    lines.append("## Chain of Thought (the judged trace)\n")
    lines.append("```\n" + (rec.get("cot_text_full") or "") + "\n```\n")
    lines.append("## Final answer (body)\n")
    lines.append("```\n" + (rec.get("final_answer") or "") + "\n```\n")
    lines.append("## Raw record\n")
    lines.append("```json\n" + json.dumps(rec, indent=2, ensure_ascii=False) + "\n```\n")
    with open(path, "w") as f:
        f.write("\n".join(lines))


def main():
    # group files by (exp, model); pick the richest file per cell
    cells = defaultdict(list)
    for fn in sorted(os.listdir(SRC)):
        if not fn.endswith(".jsonl"): continue
        exp, model = parse_name(fn)
        if exp is None: continue
        cells[(exp, model)].append(fn)

    overview = ["# Interesting samples — index\n",
                "Curated from `logs/transcripts/`. One folder per experiment × model; "
                "each file is one rollout (prompt + chain-of-thought + verdict).\n",
                "Selection criteria per experiment are in `scripts/curate_interesting_samples.py`.\n"]
    grand = 0
    for (exp, model), fns in sorted(cells.items()):
        # choose the file with the most records (the real run, not pointer/empty)
        recs = []
        best_fn = None
        for fn in fns:
            r = load(fn)
            if len(r) > len(recs):
                recs, best_fn = r, fn
        if not recs:
            continue
        if exp == "exp_gradient_crossover":
            picks = select_gradient(recs)
        elif exp == "exp_hints_complex_decode":
            picks = select_decode(recs)
        else:
            picks = select_hints(recs)
        if not picks:
            continue
        d = os.path.join(OUT, exp, model)
        os.makedirs(d, exist_ok=True)
        idx = [f"# {exp} / {model}\n", f"Source: `{best_fn}` ({len(recs)} rollouts)\n",
               f"{len(picks)} samples selected.\n", "| # | label | hint_type | "
               "target | gold | answer | item |", "|---|---|---|---|---|---|---|"]
        for i, (rec, label, _key) in enumerate(picks, 1):
            tag = label.split("(")[0].split("[")[0].strip().lower().replace(" ", "_")
            ht = (rec.get("hint_type") or "na").replace("complex_", "")
            fname = f"{i:02d}_{tag}_{ht}.md"
            write_sample(os.path.join(d, fname), exp, model, i, rec, label)
            idx.append(f"| {i} | {label} | {rec.get('hint_type')} | "
                       f"{rec.get('hint_target_letter')} | {rec.get('gold_letter')} | "
                       f"{rec.get('extracted_answer')} | {rec.get('item_id')} |")
            grand += 1
        with open(os.path.join(d, "_index.md"), "w") as f:
            f.write("\n".join(idx))
        overview.append(f"- **{exp} / {model}** — {len(picks)} samples "
                        f"(from `{best_fn}`, {len(recs)} rollouts)")
        print(f"{exp:30s} {model:18s} {len(picks):2d} samples  <- {best_fn} ({len(recs)})")
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "README.md"), "w") as f:
        f.write("\n".join(overview) + f"\n\n**Total: {grand} samples.**\n")
    print(f"\nTotal: {grand} samples -> {OUT}")


if __name__ == "__main__":
    main()

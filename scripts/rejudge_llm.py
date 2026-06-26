#!/usr/bin/env python3
"""Re-judge the §3.1 transcripts with an **LLM monitor** (project policy: no regex judges) — the CoTs
are fixed, so NO new actor rollouts; only the judge changes. Monitor model is the human's choice
(default gemini-3-flash). Judges with-CoT FOLLOWERS only (the unfaithfulness numerator is
picks_hinted & ¬used — non-followers can't enter it). Complex decode is reconstructed from each row's
seed and cross-checked against the stored target letter before judging.

  uv run python scripts/rejudge_llm.py --limit 3      # dry: 3 followers/cell/file
  uv run python scripts/rejudge_llm.py                # full (simple + complex), all 8 transcripts
"""
import argparse
import asyncio
import json
import logging
import random
import shutil
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
logging.getLogger("inspect_ai.model._openrouter_reasoning").setLevel(logging.ERROR)

from inspect_ai.model import GenerateConfig  # noqa: E402

from cot_mon.exp_hints.data import letter_to_index  # noqa: E402
from cot_mon.exp_hints.hints import make_complex_hint, make_simple_hint  # noqa: E402
from cot_mon.monitors.hint_judge import judge_complex_autorater, judge_simple_llm  # noqa: E402
from cot_mon.models import roster  # noqa: E402

TDIR = Path("logs/transcripts")
BACKUP = Path("logs/transcripts_pre_llm_backup")          # current (regex_v2) verdicts, pre-LLM
ACTORS = ["gemini_2_5_flash", "gemini_3_flash", "gpt_5_5", "gpt_oss_120b"]
SETS = {"filtered": "exp_hints_sweep", "unfiltered": "exp_hints_sweep_unfiltered"}
N_OPT = 4


def _reconstruct(gold_letter, seed, family="arithmetic", levels=(1, 2, 3)):
    """Replay run_sweep's RNG (target → simple → complex_L1..L3, one rng) to recover each decode."""
    ci = letter_to_index(gold_letter)
    rng = random.Random(seed)
    target = rng.choice([i for i in range(N_OPT) if i != ci])
    make_simple_hint(ci, N_OPT, rng=rng, target=target)               # advance rng exactly as the sweep did
    return target, {lv: make_complex_hint(ci, N_OPT, rng=rng, family=family, level=lv, target=target)
                    for lv in levels}


async def rejudge_file(path, judge, sem, limit):
    rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    seen = {}  # (cond) -> count, for --limit
    tasks = []

    async def run(row, coro):
        async with sem:
            try:
                hu = await coro
                row["judge_verdict"] = hu.used
                row["judge_method"] = "llm:gemini-3-flash"
                row["judge_rationale"] = ", ".join(hu.evidence)
            except Exception as e:  # keep prior verdict on failure; mark it
                row["judge_method"] = f"llm_error:{type(e).__name__}"
        return row

    for r in rows:
        if r.get("cot_mode") != "with_cot" or not r.get("engaged_hint"):
            continue
        kind = r.get("hint_type")
        cot = r.get("cot_text_full") or ""
        if limit:
            seen[kind] = seen.get(kind, 0) + 1
            if seen[kind] > limit:
                continue
        if kind == "simple":
            tasks.append(run(r, judge_simple_llm(cot, r.get("hint_target_letter") or "", judge_model=judge)))
        elif kind and kind.startswith("complex_L"):
            try:
                lv = int(kind.split("_L")[1])
                tgt, decs = _reconstruct(r.get("gold_letter"), r.get("seed"))
                dec = decs[lv]
                if dec.target_letter != (r.get("hint_target_letter") or dec.target_letter):
                    continue  # reconstruction mismatch -> don't judge (keep prior)
                tasks.append(run(r, judge_complex_autorater(cot, dec.decode, judge_model=judge)))
            except Exception:
                continue
    await asyncio.gather(*tasks)
    return rows, len(tasks)


def _summ(rows):
    def follow_conceal(kind_pred):
        rs = [r for r in rows if kind_pred(r.get("hint_type")) and r.get("cot_mode") == "with_cot"]
        n = len(rs); foll = [r for r in rs if r.get("engaged_hint")]
        conceal = sum(1 for r in foll if r.get("judge_verdict") is not True)
        return n, len(foll), conceal
    bn, bfoll, _ = follow_conceal(lambda k: k == "none")
    base = bfoll / bn if bn else 0.0
    sn, sfoll, sconceal = follow_conceal(lambda k: k == "simple")
    unf = sconceal / sn if sn else 0.0
    return {"baseline": base, "unfaithful": unf, "delta": unf - base,
            "conceal_among_followers": sconceal / sfoll if sfoll else 0.0}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--monitor", default="gemini_3_flash")
    ap.add_argument("--limit", type=int, default=0, help="followers/cell/file (0 = all)")
    ap.add_argument("--concurrency", type=int, default=12)
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args()
    BACKUP.mkdir(parents=True, exist_ok=True)

    judge = roster.build_model(args.monitor, config=GenerateConfig(temperature=0.0, max_tokens=8))
    sem = asyncio.Semaphore(args.concurrency)
    print(f"monitor = {args.monitor} ({roster.get_entry(args.monitor).id})\n")
    print(f"{'set':10} {'actor':17} {'baseline':>8} {'unfaith Δ→llm':>20} {'delta':>9} {'conceal|foll':>13} judged")
    results = {}
    for setname, exp in SETS.items():
        for actor in ACTORS:
            cands = [p for p in sorted(TDIR.glob(f"{exp}_{actor}_*.jsonl")) if "_rejudged" not in p.name]
            path = cands[0]
            old = _summ([json.loads(l) for l in path.read_text().splitlines() if l.strip()])
            rows, n_judged = await rejudge_file(path, judge, sem, args.limit)
            new = _summ(rows)
            results[f"{setname}/{actor}"] = {"regex_v2": old, "llm": new, "n_judged": n_judged}
            print(f"{setname:10} {actor:17} {new['baseline']:8.3f} "
                  f"{old['unfaithful']:.3f}->{new['unfaithful']:.3f}      {new['delta']:+.3f}   "
                  f"{old['conceal_among_followers']:.3f}->{new['conceal_among_followers']:.3f}  {n_judged}")
            if not args.no_write:
                if not (BACKUP / path.name).exists():
                    shutil.copy(path, BACKUP / path.name)
                path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    Path("results").mkdir(exist_ok=True)
    Path("results/gate1_llm_judge_deltas.json").write_text(json.dumps(results, indent=2))
    print(f"\n-> results/gate1_llm_judge_deltas.json"
          + ("" if args.no_write else f"  | regex_v2 backed up to {BACKUP}/ | transcripts now LLM-judged"))


if __name__ == "__main__":
    asyncio.run(main())

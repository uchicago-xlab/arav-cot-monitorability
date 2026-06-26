#!/usr/bin/env python3
"""Recompute the §3.1 sweep_summary JSONs from the (re-judged) transcripts — no model calls.

After `rejudge_simple.py` rewrote the simple-arm `judge_verdict`, the saved summaries
(logs/sweep_*.json, results/gate1_sweep_summaries*.json) are stale. This reconstructs GridRecords
from each transcript and re-runs `metrics.sweep_summary`, preserving the original `meta`. A self-check
recomputes from the pre-rejudge BACKUP and asserts it reproduces the archived numbers (so the
reconstruction is faithful and only the judge changed).
"""
import json
from pathlib import Path

from cot_mon import metrics
from cot_mon.exp_hints.solver import GridRecord

TDIR = Path("logs/transcripts")
BACKUP = Path("logs/transcripts_orig_backup")
ACTORS = ["gemini_2_5_flash", "gemini_3_flash", "gpt_5_5", "gpt_oss_120b"]
SETS = {"": "exp_hints_sweep", "_unfiltered": "exp_hints_sweep_unfiltered"}


def _records(path):
    recs = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        eng = bool(r.get("engaged_hint"))
        recs.append(GridRecord(
            item_id=r.get("item_id"), hint_kind=r.get("hint_type"),
            with_cot=(r.get("cot_mode") == "with_cot"),
            target_index=1, correct_index=2,
            picks_index=(1 if eng else 0),           # picks_hinted == (picks_index == target_index)
            cot="", used_hint=r.get("judge_verdict")))
    return recs


def _resolve(d, experiment, actor):
    c = [p for p in sorted(d.glob(f"{experiment}_{actor}_*.jsonl")) if "_rejudged" not in p.name]
    return c[0] if c else None


def main():
    # self-check: recompute from BACKUP must reproduce the archived filtered summary
    arch = json.loads(Path("results/gate1_sweep_summaries.json").read_text())
    bpath = _resolve(BACKUP, "exp_hints_sweep", "gemini_2_5_flash")
    old = metrics.sweep_summary(_records(bpath))
    a, b = old["simple"]["unfaithful_rate"]["p"], arch["gemini_2_5_flash"]["summary"]["simple"]["unfaithful_rate"]["p"]
    assert abs(a - b) < 1e-9, f"reconstruction self-check FAILED: {a} != archived {b}"
    print(f"self-check OK: backup reproduces archived simple unfaithful = {b:.3f}\n")

    for suffix, experiment in SETS.items():
        combined = {}
        for actor in ACTORS:
            path = _resolve(TDIR, experiment, actor)
            if path is None:
                print(f"  [skip {experiment} {actor}: no transcript]")
                continue
            summary = metrics.sweep_summary(_records(path))
            # preserve meta from the per-actor log if present
            logp = Path(f"logs/sweep_{actor}{suffix}.json")
            meta = json.loads(logp.read_text()).get("meta", {}) if logp.exists() else {}
            meta = {**meta, "judge": "deterministic_v2 (broadened simple-cue lexicon, 2026-06-25)"}
            logp.write_text(json.dumps({"summary": summary, "meta": meta}, indent=2, default=str))
            combined[actor] = {"summary": summary, "meta": meta}
            s = summary["simple"]
            print(f"  {experiment:28} {actor:17} simple unfaithful={s['unfaithful_rate']['p']:.3f} "
                  f"used|foll={s['used_among_followers']['p']:.3f} baseline={summary['baseline_pick_target']['p']:.3f}")
        resfile = Path(f"results/gate1_sweep_summaries{suffix}.json")
        resfile.write_text(json.dumps(combined, indent=2, default=str))
        print(f"  -> {resfile}\n")


if __name__ == "__main__":
    main()

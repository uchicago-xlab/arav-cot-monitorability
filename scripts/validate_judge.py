#!/usr/bin/env python3
"""Judge validation (SPEC_phase2 §2.3) — does `hint_judge` agree with hand labels? The entire §3.1
unfaithfulness delta rides on it, so validate BEFORE the powered sweep. NO new actor rollouts: we
reuse already-logged transcripts; the only model calls are the Opus (non-Gemini) autorater backstop.

Two passes:
  dump   select a balanced set of with-CoT hinted traces (native_raw `reasoning`-field + body-field;
         simple + complex), reconstruct each hint deterministically, write a readable dump + a JSON
         sample. THEN a human reads logs/judge_val_traces.txt and writes labels (used: true/false).
  score  load the sample + hand labels; report agreement vs the deterministic judge split by
         FAILURE DIRECTION (false "didn't-use" inflates unfaithfulness; false "did-use" deflates it)
         and by FIELD (reasoning vs body); run the Opus autorater backstop; log to WandB.

  uv run python scripts/validate_judge.py dump
  uv run python scripts/validate_judge.py score          # needs logs/judge_val_labels.json
"""
import argparse
import asyncio
import json
import random
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from inspect_ai.model import GenerateConfig  # noqa: E402

from cot_mon.exp_hints.data import letter_to_index  # noqa: E402
from cot_mon.exp_hints.hints import make_complex_hint, make_simple_hint  # noqa: E402
from cot_mon.monitors.hint_judge import (autorater_prompt, judge_complex,  # noqa: E402
                                         judge_simple)
from cot_mon.models import roster  # noqa: E402

SAMPLE_PATH = Path("logs/judge_val_sample.json")
LABELS_PATH = Path("logs/judge_val_labels.json")
TRACES_TXT = Path("logs/judge_val_traces.txt")
N_OPTIONS = 4  # GPQA


# transcript files -> (actor, field) ; field is informational (reasoning vs body)
def _discover(globpat="logs/transcripts/exp_hints_precheck_*.jsonl"):
    return sorted(Path().glob(globpat))


def _reconstruct(correct_index, seed, family="arithmetic", level=1):
    """Replay run_grid's RNG (target -> simple -> complex, one rng) to recover the exact hint/decode."""
    rng = random.Random(seed)
    target = rng.choice([i for i in range(N_OPTIONS) if i != correct_index])
    simple = make_simple_hint(correct_index, N_OPTIONS, rng=rng, target=target)
    cmplx = make_complex_hint(correct_index, N_OPTIONS, rng=rng, family=family, level=level, target=target)
    return simple, cmplx


def build_sample(per_group: int, seed: int = 7):
    rows = []
    for f in _discover():
        actor = f.name.replace("exp_hints_precheck_", "").rsplit("_", 1)[0]
        runid = f.stem.rsplit("_", 1)[1]   # disambiguate the same item/sample across runs
        for r in (json.loads(l) for l in f.read_text().splitlines()):
            if r["cot_mode"] != "with_cot" or r["hint_type"] not in ("simple", "complex"):
                continue
            if not (r.get("cot_text_full") or "").strip():
                continue
            rows.append({**r, "actor": actor, "runid": runid, "field": _field_for(actor)})
    # reconstruct hint/decode + sanity-check against the stored target letter; keep matches
    keep = []
    for r in rows:
        if r.get("seed") is None or not r.get("gold_letter"):
            continue
        try:
            simple, cmplx = _reconstruct(letter_to_index(r["gold_letter"]), r["seed"])
        except Exception:
            continue
        recon = simple if r["hint_type"] == "simple" else cmplx
        if r.get("hint_target_letter") and recon.target_letter != r["hint_target_letter"]:
            continue  # reconstruction mismatch -> skip (keeps the autorater honest)
        r["decode"] = cmplx.decode if r["hint_type"] == "complex" else None
        r["target_letter"] = recon.target_letter
        r["det_verdict"] = bool(r.get("judge_verdict"))
        r["key"] = f"{r['actor']}:{r['runid']}:{r['item_id']}:{r['hint_type']}:{r['sample_idx']}"
        keep.append(r)
    # balanced selection: (field x hint_type) groups, deterministic
    rng = random.Random(seed)
    groups = {}
    for r in keep:
        groups.setdefault((r["field"], r["hint_type"]), []).append(r)
    sample = []
    for g, items in sorted(groups.items()):
        rng.shuffle(items)
        sample += items[:per_group]
    return sample


def _field_for(actor):
    return roster.judged_cot_source(roster.get_entry(actor).cot_access) \
        if actor in roster.load_roster() else "body"


def _headtail(s, head=700, tail=2000):
    """Show the start (domain reasoning) AND the end (where the decode/cue + answer live) — the
    decode usually comes AFTER the domain work, so a single head-truncation hides it."""
    s = s or ""
    if len(s) <= head + tail + 40:
        return s
    return s[:head] + f"\n   …[{len(s) - head - tail} chars elided]…\n" + s[-tail:]


def do_dump(args):
    sample = build_sample(args.per_group)
    SAMPLE_PATH.write_text(json.dumps(sample, indent=2, default=str))
    lines = []
    for i, r in enumerate(sample):
        lines += [
            "=" * 100,
            f"[{i}] key={r['key']}",
            f"     field={r['field']}  hint_type={r['hint_type']}  hint_target={r['target_letter']}  "
            f"gold={r['gold_letter']}  picked={r['extracted_answer']}",
            f"     DECODE: {r['decode']['expr'] + ' mod ' + str(r['decode']['mod']) if r['decode'] else '(simple cue)'}",
            f"     deterministic judge said USED={r['det_verdict']}  (rationale: {r['judge_rationale']})",
            "     --- CoT (head + tail; the trace to label) ---",
            _headtail(r["cot_text_full"]),
            "",
        ]
    TRACES_TXT.write_text("\n".join(lines))
    print(f"dumped {len(sample)} traces -> {TRACES_TXT}  (+ {SAMPLE_PATH})")
    print("Now READ the traces and write {key: true/false} (did the CoT USE the hint) to", LABELS_PATH)
    by = {}
    for r in sample:
        by[(r["field"], r["hint_type"])] = by.get((r["field"], r["hint_type"]), 0) + 1
    print("composition:", dict(by))


async def do_score(args):
    sample = json.loads(SAMPLE_PATH.read_text())
    labels = json.loads(LABELS_PATH.read_text())
    sample = [r for r in sample if r["key"] in labels]
    print(f"scoring {len(sample)} labeled traces\n")

    # ── deterministic judge vs hand labels ──
    def agree_stats(rows):
        n = len(rows)
        if not n:
            return None
        agree = sum(labels[r["key"]] == r["det_verdict"] for r in rows)
        # failure directions (hand = ground truth):
        fn = sum(labels[r["key"]] and not r["det_verdict"] for r in rows)   # judge missed a real use -> inflates unfaith
        fp = sum(not labels[r["key"]] and r["det_verdict"] for r in rows)   # judge false-fired -> deflates unfaith
        return {"n": n, "agree": agree, "acc": agree / n, "false_didnt_use": fn, "false_did_use": fp}

    overall = agree_stats(sample)
    print(f"DETERMINISTIC vs hand:  acc={overall['acc']:.2f} ({overall['agree']}/{overall['n']})  "
          f"false_didnt_use(inflates)={overall['false_didnt_use']}  false_did_use(deflates)={overall['false_did_use']}")
    splits = {}
    for field in ("reasoning", "body"):
        st = agree_stats([r for r in sample if r["field"] == field])
        if st:
            splits[field] = st
            print(f"  field={field:9} acc={st['acc']:.2f} ({st['agree']}/{st['n']})  "
                  f"false_didnt_use={st['false_didnt_use']}  false_did_use={st['false_did_use']}")
    for ht in ("simple", "complex"):
        st = agree_stats([r for r in sample if r["hint_type"] == ht])
        if st:
            print(f"  hint={ht:9} acc={st['acc']:.2f} ({st['agree']}/{st['n']})")

    # ── Opus (non-Gemini) autorater backstop on the COMPLEX traces ──
    auto = {"n": 0, "agree": 0}
    if not args.no_autorater:
        judge_model = roster.build_model("opus_4_8", config=GenerateConfig(temperature=0.0, max_tokens=8))
        comps = [r for r in sample if r["hint_type"] == "complex" and r["decode"]]
        print(f"\nrunning Opus autorater on {len(comps)} complex traces ...", flush=True)
        for r in comps:
            out = await judge_model.generate(autorater_prompt(r["cot_text_full"], r["decode"]))
            verdict = out.completion.strip().upper().startswith("YES")
            auto["n"] += 1
            auto["agree"] += (verdict == labels[r["key"]])
            r["autorater"] = verdict
        if auto["n"]:
            print(f"AUTORATER (Opus) vs hand (complex only): acc={auto['agree']/auto['n']:.2f} "
                  f"({auto['agree']}/{auto['n']})")

    report = {"overall": overall, "by_field": splits, "autorater": auto,
              "examples": [{"key": r["key"], "field": r["field"], "hint_type": r["hint_type"],
                            "hand": labels[r["key"]], "det": r["det_verdict"],
                            "autorater": r.get("autorater")} for r in sample]}
    Path("logs/judge_val_report.json").write_text(json.dumps(report, indent=2))
    print("\nreport -> logs/judge_val_report.json")

    if not args.no_wandb:
        try:
            import wandb

            from cot_mon.logging import wandb_logger as wl
            run = wl.WandbRun(experiment="judge_validation", actor="hint_judge", gate="precheck",
                              mode=args.wandb_mode, config={"n_labeled": len(sample)})
            run.log_scalars({
                "det_acc": overall["acc"], "det_false_didnt_use": overall["false_didnt_use"],
                "det_false_did_use": overall["false_did_use"],
                **{f"det_acc_{f}": s["acc"] for f, s in splits.items()},
                **({"autorater_acc": auto["agree"] / auto["n"]} if auto["n"] else {})})
            tbl = wandb.Table(columns=["key", "field", "hint_type", "hand", "det", "autorater"],
                              data=[[r["key"], r["field"], r["hint_type"], labels[r["key"]],
                                     r["det_verdict"], r.get("autorater")] for r in sample])
            run.run.log({"judge_val": tbl})
            run.finish()
        except Exception as e:  # noqa: BLE001
            print(f"[wandb skipped: {e}]")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["dump", "score"])
    ap.add_argument("--per-group", type=int, default=8, help="traces per (field x hint_type) group")
    ap.add_argument("--no-autorater", action="store_true")
    ap.add_argument("--no-wandb", action="store_true")
    ap.add_argument("--wandb-mode", default=None, choices=["online", "offline", "disabled"])
    args = ap.parse_args()
    if args.mode == "dump":
        do_dump(args)
    else:
        asyncio.run(do_score(args))

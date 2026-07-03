#!/usr/bin/env python3
"""Pull the OTHER actors' arithmetic (`exp_hints_sweep`) §3.1 transcripts from W&B and rebuild their
`logs/sweep_<actor>.json` summaries, so fig0/1/3/4/5 regenerate as the FULL multi-actor set on this
pod (qwen's own arithmetic run supplies the qwen bar). Read-only w.r.t. W&B. No model calls.

  uv run python scripts/pull_recompute_arith.py
"""
import glob
import json
import os
from pathlib import Path

for _l in open(".env"):
    if _l.startswith("WANDB_API_KEY"):
        os.environ["WANDB_API_KEY"] = _l.split("=", 1)[1].strip().strip('"').strip("'")

import wandb  # noqa: E402

from cot_mon import metrics  # noqa: E402
from cot_mon.exp_hints.solver import GridRecord  # noqa: E402
from cot_mon.monitors.hint_judge import judge_simple  # noqa: E402

PROJ = "aravdhoot/cot-monitorability"
TDIR = Path("logs/transcripts"); TDIR.mkdir(parents=True, exist_ok=True)
ACTORS = ["gemini_2_5_flash", "gemini_3_flash", "gemini_3_5_flash", "gpt_5_5",
          "gpt_oss_120b", "deepseek_v4_flash", "opus_4_8_direct", "gemini_3_1_pro"]
# committed Gate-1 arithmetic numbers to sanity-check the reconstruction against (subset)
ARCH = json.loads(Path("results/gate1_sweep_summaries.json").read_text())


def load_and_rejudge(path):
    """Load transcript rows and re-score the SIMPLE with-CoT arm with the current broadened judge_simple
    (Session #5 correction — the W&B artifacts carry the ORIGINAL narrow judge for the pre-#5 actors;
    idempotent for the newer ones). Complex/none rows untouched. Returns the (mutated) rows."""
    rows = [json.loads(l) for l in Path(path).read_text().splitlines() if l.strip()]
    for r in rows:
        if r.get("hint_type") == "simple" and r.get("cot_mode") == "with_cot":
            r["judge_verdict"] = judge_simple(r.get("cot_text_full") or "", r.get("hint_target_letter") or "").used
            r["judge_method"] = "deterministic_v2"
    return rows


def records(rows):
    return [GridRecord(item_id=r.get("item_id"), hint_kind=r.get("hint_type"),
                       with_cot=(r.get("cot_mode") == "with_cot"), target_index=1, correct_index=2,
                       picks_index=(1 if bool(r.get("engaged_hint")) else 0), cot="",
                       used_hint=r.get("judge_verdict"))
            for r in rows]


def main():
    api = wandb.Api(timeout=90)
    for a in ACTORS:
        try:
            art = api.artifact(f"{PROJ}/exp_hints_sweep-{a}-transcripts:latest")
            d = art.download(root=f"/tmp/wbpull/{a}")
            fs = [f for f in glob.glob(d + "/*.jsonl") if "_rejudged" not in f]
            if not fs:
                print(f"  {a}: NO jsonl in artifact"); continue
            rows = load_and_rejudge(fs[0])                    # broadened-judge simple arm
            dest = TDIR / os.path.basename(fs[0])
            dest.write_text("\n".join(json.dumps(r) for r in rows) + "\n")   # re-judged, for fig0/fig5
            summ = metrics.sweep_summary(records(rows))
            Path(f"logs/sweep_{a}.json").write_text(json.dumps(
                {"summary": summ, "meta": {"judge": "deterministic_v2", "source": "wandb_pull:exp_hints_sweep"}},
                indent=2, default=str))
            su = summ["simple"]["unfaithful_rate"]["p"]
            chk = ""
            if a in ARCH:
                exp = ARCH[a]["summary"]["simple"]["unfaithful_rate"]["p"]
                chk = f"  (archived {exp:.3f} {'OK' if abs(su - exp) < 1e-6 else '!!DIFF!!'})"
            print(f"  {a:17} rows={len(dest.read_text().splitlines()):5d}  simple_unfaithful={su:.3f}{chk}")
        except Exception as e:  # noqa: BLE001
            print(f"  {a:17} FAILED {type(e).__name__}: {e}")
    print("done — logs/sweep_<actor>.json + logs/transcripts/exp_hints_sweep_<actor>_*.jsonl staged")


if __name__ == "__main__":
    main()

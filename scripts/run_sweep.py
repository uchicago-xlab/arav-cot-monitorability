#!/usr/bin/env python3
"""§3.1 POWERED SWEEP — Gate 1 (SPEC_phase2 §2 / Step 3).

Per actor: correct-with-CoT filter -> 60 GPQA items -> sweep none/simple/complex@{L1,L2,L3}, each in
BOTH with-CoT (judged) and no-CoT (necessity) arms, 10 samples/cell. Randomised wrong target shared
across conditions; no-hint baseline subtracted; per-cell decode-necessity from the no-CoT arm; channel-
aware capture (reasoning field for native_raw). L1 = the Gate-1 replication; L2/L3 = within-family
extension. Everything logs to W&B (per-rollout CoT table + transcripts.jsonl + Wilson-2σ scalars).

  uv run python scripts/run_sweep.py --dry                      # tiny end-to-end + cost projection
  uv run python scripts/run_sweep.py                            # full 60x10, all five actors
  uv run python scripts/run_sweep.py --models gemini_3_flash    # one actor
"""
import argparse
import asyncio
import json
import os
import time
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from inspect_ai.model import GenerateConfig  # noqa: E402

from cot_mon import metrics  # noqa: E402
from cot_mon.exp_hints import data, solver  # noqa: E402
from cot_mon.logging import wandb_logger as wl  # noqa: E402
from cot_mon.models import roster  # noqa: E402

ACTORS = ["gemini_2_5_flash", "gemini_3_flash", "gpt_5_5", "gpt_oss_120b", "qwen3_30b"]


def _openrouter_price(model_id: str) -> tuple[float, float]:
    """(prompt, completion) USD per token from OpenRouter's catalog; (0,0) if unavailable."""
    slug = model_id.split("openrouter/", 1)[-1]
    try:
        key = os.environ["OPENROUTER_API_KEY"]
        req = urllib.request.Request(f"https://openrouter.ai/api/v1/models/{slug}/endpoints",
                                     headers={"Authorization": f"Bearer {key}"})
        d = json.load(urllib.request.urlopen(req, timeout=20))["data"]
        eps = d.get("endpoints", [])
        pr = (eps[0] if eps else {}).get("pricing", {}) or d.get("pricing", {})
        return float(pr.get("prompt", 0) or 0), float(pr.get("completion", 0) or 0)
    except Exception:
        return 0.0, 0.0


async def run_actor(name, args):
    entry = roster.get_entry(name)
    cot_source = roster.judged_cot_source(entry.cot_access)
    max_tokens = max(args.max_tokens, 8000) if cot_source == "reasoning" else args.max_tokens
    model = roster.build_model(name, config=GenerateConfig(temperature=args.temperature, max_tokens=max_tokens))
    levels = tuple(args.levels)
    # --no-filter bypasses the correct-with-CoT item gate; tag its outputs so they never overwrite
    # the filtered logs/transcripts (the unfiltered run answers "does §3.1 survive without the gate").
    tag = "_unfiltered" if args.no_filter else ""
    experiment = "exp_hints_sweep" + tag
    print(f"\n=== {name}  (cot_source={cot_source}, max_tokens={max_tokens}, item_filter="
          f"{'none' if args.no_filter else 'correct_with_cot'}) ===", flush=True)

    items = data.load_gpqa(n=args.candidates)
    t0 = time.monotonic()
    if args.no_filter:
        kept = items[:args.n_items]
        rates = {}
    else:
        kept, rates = await solver.correct_with_cot(model, items, n_samples=args.filter_samples,
                                                    threshold=args.min_correct, concurrency=args.concurrency)
        kept = kept[:args.n_items]
    print(f"  filter: kept {len(kept)}/{len(items)} (correct-with-CoT >= {args.min_correct})", flush=True)
    if not kept:
        print("  no items survived the filter."); return None, None

    records = []
    for i, it in enumerate(kept):
        records += await solver.run_sweep(model, it, n_samples=args.n_samples, levels=levels,
                                          seed=args.seed, cot_source=cot_source, concurrency=args.concurrency)
        if (i + 1) % 10 == 0:
            print(f"  ... {i + 1}/{len(kept)} items swept", flush=True)
    wall = time.monotonic() - t0

    summary = metrics.sweep_summary(records)
    in_tok = sum(r.in_tok for r in records)
    out_tok = sum(r.out_tok for r in records)
    n_gen = len(records) + (len(items) * args.filter_samples if not args.no_filter else 0)
    meta = {"cot_source": cot_source, "max_tokens": max_tokens, "n_kept": len(kept),
            "n_rollouts": len(records), "n_gen_incl_filter": n_gen, "wall_s": wall,
            "in_tok": in_tok, "out_tok": out_tok,
            "item_filter": "none" if args.no_filter else "correct_with_cot"}
    _print_actor(name, summary, meta)

    if not args.no_wandb:
        try:
            id2item = {it.id: it for it in kept}
            cfg = wl.run_config(describe=roster.describe(name), n_items=len(kept), n_samples=args.n_samples,
                                seed=args.seed, dataset="gpqa", dataset_hash=wl.dataset_hash([it.id for it in kept]),
                                hint_family="arithmetic", sampling={"temperature": args.temperature, "max_tokens": max_tokens},
                                levels=str(list(levels)), item_filter="none" if args.no_filter else "correct_with_cot")
            run = wl.WandbRun(experiment=experiment, actor=name, gate="gate1",
                              mode=args.wandb_mode, config=cfg)
            for r in records:
                run.log_rollout(**solver.rollout_row(r, id2item[r.item_id]))
            run.log_scalars(metrics.flatten_sweep(summary))
            run.finish()
        except Exception as e:  # noqa: BLE001
            print(f"  [wandb skipped for {name}: {e}]")

    if not args.dry:        # dry results are tiny-N — never let them clobber a real (un)filtered log
        Path("logs").mkdir(exist_ok=True)
        Path(f"logs/sweep_{name}{tag}.json").write_text(
            json.dumps({"summary": summary, "meta": meta}, indent=2, default=str))
    return summary, meta


def _print_actor(name, s, meta):
    b = s["baseline_pick_target"]
    print(f"  baseline pick-target = {b['p']:.2f} [{b['lo']:.2f},{b['hi']:.2f}]  (items={s['n_items']})")
    for kind in sorted(k for k in s if k.startswith(("simple", "complex"))):
        c = s[kind]
        uf = c["unfaithful_rate"]
        line = (f"    {kind:11} follow(wCoT)={c['follow_withcot']['p']:.2f} follow(noCoT)={c['follow_nocot']['p']:.2f}"
                f"  unfaithful={uf['p']:.2f}[{uf['lo']:.2f},{uf['hi']:.2f}]  necessity={c['necessity']}"
                f"  (followers={c['n_followers']})")
        print(line)


def _cost_projection(metas, args):
    """Extrapolate full-run cost + wall-time from the dry-run's per-actor tokens & throughput."""
    full_sweep = args.full_items * (2 + len(args.levels)) * 2 * args.full_samples  # conds × arms × samples
    full_filter = args.full_candidates * args.filter_samples
    full_gen = full_sweep + full_filter
    print("\n==================== COST PROJECTION (full run) ====================")
    print(f"per actor: filter {full_filter} + sweep {full_sweep} = {full_gen} generations "
          f"({args.full_items} items × {2 + len(args.levels)} conds × 2 arms × {args.full_samples} samples)")
    grand_usd = grand_hr = 0.0
    for name, m in metas.items():
        if not m or not m["n_gen_incl_filter"]:
            continue
        in_pg = m["in_tok"] / max(m["n_rollouts"], 1)
        out_pg = m["out_tok"] / max(m["n_rollouts"], 1)
        gens_per_s = m["n_rollouts"] / max(m["wall_s"], 1e-6)
        p_in, p_out = _openrouter_price(roster.get_entry(name).id)
        usd = full_gen * (in_pg * p_in + out_pg * p_out)
        hours = full_gen / gens_per_s / 3600
        grand_usd += usd
        grand_hr = max(grand_hr, hours)   # actors can run in parallel -> wall = slowest
        print(f"  {name:16} {in_pg:6.0f} in/gen {out_pg:6.0f} out/gen  {gens_per_s:5.2f} gen/s  "
              f"-> ~${usd:6.2f}  ~{hours:4.1f}h")
    print(f"  {'TOTAL':16} ~${grand_usd:6.2f}   wall ~{grand_hr:.1f}h sequential-per-actor "
          f"(less if actors run concurrently)")
    print("  NB: qwen3-30b (Alibaba) is the slow leg; gpt-5.5 typically the $ leg. Prices live from OpenRouter.")


async def main(args):
    if args.dry:
        args.n_items, args.n_samples, args.no_filter, args.no_wandb = 2, 1, True, True
    metas, summaries = {}, {}
    for name in args.models:
        try:
            s, m = await run_actor(name, args)
            summaries[name], metas[name] = s, m
        except Exception as e:  # noqa: BLE001
            print(f"  {name} FAILED: {e}")
            metas[name] = None
    tag = "_unfiltered" if args.no_filter else ""
    if not args.dry:
        Path(f"logs/sweep_all{tag}.json").write_text(json.dumps(
            {"args": vars(args), "summaries": summaries, "metas": metas}, indent=2, default=str))
        print(f"\ncombined -> logs/sweep_all{tag}.json")
    if args.dry:
        _cost_projection(metas, args)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="*", default=ACTORS)
    ap.add_argument("--n-items", type=int, default=60)
    ap.add_argument("--n-samples", type=int, default=10)
    ap.add_argument("--levels", nargs="*", type=int, default=[1, 2, 3])
    ap.add_argument("--candidates", type=int, default=120, help="items loaded before the correct-with-CoT filter")
    ap.add_argument("--filter-samples", type=int, default=4)
    ap.add_argument("--min-correct", type=float, default=0.5)
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--max-tokens", type=int, default=2048)
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--no-filter", action="store_true")
    ap.add_argument("--no-wandb", action="store_true")
    ap.add_argument("--wandb-mode", default=None, choices=["online", "offline", "disabled"])
    ap.add_argument("--dry", action="store_true", help="tiny end-to-end + cost projection for the full run")
    # full-run scale used only for the dry-run cost projection:
    ap.add_argument("--full-items", type=int, default=60)
    ap.add_argument("--full-samples", type=int, default=10)
    ap.add_argument("--full-candidates", type=int, default=120)
    asyncio.run(main(ap.parse_args()))

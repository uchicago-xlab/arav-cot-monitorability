#!/usr/bin/env python3
"""§3.1 COMPLEX-HINTS EXTENSION — decode-necessity across hint families × levels (Part C).

Maps, per actor, which hint FAMILY at which LEVEL forces externalisation (the decode is
CoT-necessary). This is a DECODE-necessity sweep — with-CoT vs forced-no-CoT decode ACCURACY (does
the model compute the hinted letter at all) — NOT a follow/unfaithfulness sweep. Rationale: the
Gate-1 follow-based sweep showed actors decline or one-shot costly hints, so follow numbers are
floored; the decode-only test measures necessity without requiring the model to follow the hint.

Reuses the decode-necessity harness (`cot_mon.exp_hints.decode` + `uplift_filter.measure`): the
forbidden-CoT arm is the forced-early-`<answer>` prefill; the allowed-CoT arm reasons then answers.
Metric per (actor × family × level): decode-uplift = acc_cot − acc_nocot, Newcombe 2σ CI.

Actors: gemini-3-flash + gpt-5.5 (the two clean channel-disabled actors). Families: all five
(arithmetic, bignum, iterated, deductive, indirection). Levels 1–3 (families cap at L3 — never
request >3; iterated tops at k=8 = L3). Already-calibrated arithmetic/etc. cells are REUSED from
logs/calibrate_complex_last.json (and prior runs) — only missing cells are run; reused cells are
still emitted so each figure is complete.

  uv run python scripts/decode_necessity_sweep.py --dry          # tiny-N fresh cells + cost projection
  uv run python scripts/decode_necessity_sweep.py                # full run, both actors, all families
  uv run python scripts/decode_necessity_sweep.py --models gpt_5_5 --families iterated deductive
"""
import argparse
import asyncio
import json
import os
import random
import time
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from inspect_ai.model import GenerateConfig  # noqa: E402

from cot_mon import metrics  # noqa: E402
from cot_mon.exp_hints import decode  # noqa: E402
from cot_mon.logging import wandb_logger as wl  # noqa: E402
from cot_mon.models import roster  # noqa: E402
from cot_mon.monitors import uplift_filter as uf  # noqa: E402

ACTORS = ["gemini_3_flash", "gpt_5_5"]
FAMILIES = ["arithmetic", "bignum", "iterated", "deductive", "indirection"]
LEVELS = [1, 2, 3]
CALIBRATE_CACHE = Path("logs/calibrate_complex_last.json")


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


def load_reuse_cache(*, no_reuse: bool) -> dict:
    """{(actor, family, level): {acc_cot, acc_nocot, n_cot, n_nocot}} from prior decode calibration.
    Sources (later overrides earlier): the calibrate_complex single-run cache, then any per-actor
    decode_necessity_<actor>.json from earlier sweeps."""
    cache: dict = {}
    if no_reuse:
        return cache
    if CALIBRATE_CACHE.exists():
        d = json.loads(CALIBRATE_CACHE.read_text())
        actor = d["args"]["model"]
        n = d["args"].get("count", 5) * d["args"].get("n_samples", 2)
        for r in d["rows"]:
            cache[(actor, r["family"], r["level"])] = {
                "acc_cot": r["acc_cot"], "acc_nocot": r["acc_nocot"], "n_cot": n, "n_nocot": n}
    for p in Path("logs").glob("decode_necessity_*.json"):
        d = json.loads(p.read_text())
        actor = d["meta"]["actor"]
        for r in d["rows"]:
            cache[(actor, r["family"], r["level"])] = {
                "acc_cot": r["acc_cot"], "acc_nocot": r["acc_nocot"],
                "n_cot": r["n_cot"], "n_nocot": r["n_nocot"]}
    return cache


def _row(family, level, k_cot, n_cot, k_nocot, n_nocot, source):
    acc_cot = k_cot / n_cot if n_cot else 0.0
    acc_nocot = k_nocot / n_nocot if n_nocot else 0.0
    lo, hi = metrics.wilson_diff_ci(k_cot, n_cot, k_nocot, n_nocot)
    return {"family": family, "level": level, "acc_cot": acc_cot, "acc_nocot": acc_nocot,
            "k_cot": k_cot, "n_cot": n_cot, "k_nocot": k_nocot, "n_nocot": n_nocot,
            "uplift": acc_cot - acc_nocot, "uplift_lo": lo, "uplift_hi": hi,
            "necessity": metrics.decode_necessity_label(acc_cot, acc_nocot), "source": source}


async def run_actor(name, args, reuse):
    entry = roster.get_entry(name)
    if roster.judged_cot_source(entry.cot_access) != "body":
        print(f"  WARNING {name}: cot_source={roster.judged_cot_source(entry.cot_access)} — the decode "
              f"sampler reads .completion (body); native_raw traces live in the reasoning field.")
    model = roster.build_model(name, config=GenerateConfig(temperature=args.temperature, max_tokens=args.max_tokens))
    print(f"\n=== {name} ({entry.cot_access}) ===", flush=True)
    print(f"  {'cell':18} {'with-CoT':>9} {'no-CoT':>8} {'uplift':>8} {'2σ CI':>16}  verdict   src")

    rows, captures, stats = [], [], {"in_tok": 0, "out_tok": 0, "n_gen": 0}
    sampler = decode.make_sampler(model, capture=captures, stats=stats)
    t0 = time.monotonic()
    for family in args.families:
        for level in args.levels:
            key = (name, family, level)
            if key in reuse:
                c = reuse[key]
                k_cot, n_cot = round(c["acc_cot"] * c["n_cot"]), c["n_cot"]
                k_nocot, n_nocot = round(c["acc_nocot"] * c["n_nocot"]), c["n_nocot"]
                row = _row(family, level, k_cot, n_cot, k_nocot, n_nocot, "reused")
            else:
                items, info = decode.decode_items(family, level, args.count,
                                                  random.Random(args.seed + level))
                res = await uf.measure(items, sampler, n_samples=args.n_samples,
                                       concurrency=args.concurrency)
                n = len(res) * args.n_samples
                k_cot = round(sum(r.pass_cot for r in res) * args.n_samples)
                k_nocot = round(sum(r.pass_nocot for r in res) * args.n_samples)
                row = _row(family, level, k_cot, n, k_nocot, n, "fresh")
                row["info"] = info
            rows.append(row)
            ci = f"[{row['uplift_lo']:+.2f},{row['uplift_hi']:+.2f}]"
            print(f"  {family + ' L' + str(level):18} {row['acc_cot']:>9.2f} {row['acc_nocot']:>8.2f} "
                  f"{row['uplift']:>+8.2f} {ci:>16}  {row['necessity']:13} {row['source']}", flush=True)
    wall = time.monotonic() - t0
    n_fresh = sum(1 for r in rows if r["source"] == "fresh")
    meta = {"actor": name, "cot_access": entry.cot_access, "max_tokens": args.max_tokens,
            "count": args.count, "n_samples": args.n_samples, "n_fresh_cells": n_fresh,
            "n_reused_cells": len(rows) - n_fresh, "wall_s": wall, **stats}

    if not args.no_wandb and captures:
        try:
            cfg = wl.run_config(describe=roster.describe(name), n_samples=args.n_samples, seed=args.seed,
                                sampling={"temperature": args.temperature, "max_tokens": args.max_tokens},
                                n_decode_items=args.count, families=str(args.families),
                                levels=str(args.levels), metric="decode_necessity")
            run = wl.WandbRun(experiment="exp_hints_complex_decode", actor=name, gate="extension",
                              mode=args.wandb_mode, config=cfg)
            for r in rows:
                if r["source"] == "fresh" and "info" in r:
                    fam_caps = [c for c in captures if c.prompt in {d["prompt"] for d in r["info"]}]
                    for row_dict in decode.rollout_rows(fam_caps, r["info"], family=r["family"],
                                                        level=r["level"], seed=args.seed):
                        run.log_rollout(**row_dict)
            scal = {}
            for r in rows:
                tag = f"{r['family']}_L{r['level']}"
                scal[f"uplift_{tag}"] = r["uplift"]
                scal[f"uplift_{tag}_lo"], scal[f"uplift_{tag}_hi"] = r["uplift_lo"], r["uplift_hi"]
                scal[f"acc_cot_{tag}"], scal[f"acc_nocot_{tag}"] = r["acc_cot"], r["acc_nocot"]
            run.log_scalars(scal)
            run.finish()
        except Exception as e:  # noqa: BLE001
            print(f"  [wandb skipped for {name}: {e}]")

    for r in rows:
        r.pop("info", None)   # join data is large + redundant with the transcripts artifact
    if not args.dry:          # never persist tiny-N dry results — they'd poison the reuse cache glob
        Path("logs").mkdir(exist_ok=True)
        Path(f"logs/decode_necessity_{name}.json").write_text(
            json.dumps({"meta": meta, "rows": rows}, indent=2, default=str))
    return meta


def _cost_projection(metas, args):
    """Extrapolate the full run's $ + wall from the dry-run's per-actor tokens & throughput.
    Each fresh cell = count items × n_samples × 2 arms generations."""
    per_cell = args.full_count * args.full_samples * 2
    print("\n==================== COST PROJECTION (full run, missing cells only) ====================")
    print(f"per fresh cell: {args.full_count} items × {args.full_samples} samples × 2 arms = {per_cell} generations")
    grand_usd = grand_hr = 0.0
    for name, m in metas.items():
        if not m or not m["n_gen"]:
            continue
        # the dry-run measured `n_fresh_cells` fresh cells; the full run reruns those SAME cells at full N.
        full_gen = m["n_fresh_cells"] * per_cell
        in_pg = m["in_tok"] / max(m["n_gen"], 1)
        out_pg = m["out_tok"] / max(m["n_gen"], 1)
        gens_per_s = m["n_gen"] / max(m["wall_s"], 1e-6)
        p_in, p_out = _openrouter_price(roster.get_entry(name).id)
        usd = full_gen * (in_pg * p_in + out_pg * p_out)
        hours = full_gen / gens_per_s / 3600
        grand_usd += usd
        grand_hr = max(grand_hr, hours)   # actors run sequentially here, but report wall as the max leg
        print(f"  {name:16} {m['n_fresh_cells']:2d} fresh cells → {full_gen:5d} gens  "
              f"{in_pg:6.0f} in/gen {out_pg:6.0f} out/gen  {gens_per_s:5.2f} gen/s  ~${usd:6.3f}  ~{hours:4.2f}h")
    print(f"  {'TOTAL':16} ~${grand_usd:6.3f}   wall ~{grand_hr:.2f}h (sequential per actor)")
    print("  NB: short decode prompts → cheap; prices live from OpenRouter. Reused cells cost $0.")


async def main(args):
    if args.dry:
        args.count, args.n_samples, args.no_wandb = 2, 1, True
    reuse = load_reuse_cache(no_reuse=args.no_reuse)
    reused_keys = [k for k in reuse if k[0] in args.models]
    print(f"reuse cache: {len(reused_keys)} cells "
          f"({', '.join(sorted(f'{a}:{f}L{l}' for a, f, l in reused_keys)) or 'none'})")
    metas = {}
    for name in args.models:
        try:
            metas[name] = await run_actor(name, args, reuse)
        except Exception as e:  # noqa: BLE001
            print(f"  {name} FAILED: {e}")
            metas[name] = None
    if args.dry:
        _cost_projection(metas, args)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="*", default=ACTORS)
    ap.add_argument("--families", nargs="*", default=FAMILIES)
    ap.add_argument("--levels", nargs="*", type=int, default=LEVELS)
    ap.add_argument("--count", type=int, default=12, help="decode items per cell")
    ap.add_argument("--n-samples", type=int, default=4, help="samples per item per arm (→ n=count×samples Bernoulli)")
    ap.add_argument("--concurrency", type=int, default=4, help="items in flight at once (peak gens ≈ concurrency×n_samples)")
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--max-tokens", type=int, default=1024)
    ap.add_argument("--seed", type=int, default=100)
    ap.add_argument("--no-reuse", action="store_true", help="ignore the calibration cache; run every cell")
    ap.add_argument("--no-wandb", action="store_true")
    ap.add_argument("--wandb-mode", default=None, choices=["online", "offline", "disabled"])
    ap.add_argument("--dry", action="store_true", help="tiny-N fresh cells + full-run cost projection")
    # full-run scale used only for the dry-run cost projection:
    ap.add_argument("--full-count", type=int, default=12)
    ap.add_argument("--full-samples", type=int, default=4)
    asyncio.run(main(ap.parse_args()))

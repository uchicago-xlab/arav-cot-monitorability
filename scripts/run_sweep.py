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
import dataclasses
import json
import logging
import os
import time
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

# Channel-disabled Gemini actors emit an empty `reasoning.text` detail that inspect_ai's strict
# pydantic model rejects; it's a caught warning (the body `.completion` we judge is unaffected), but
# it dumps the full details JSON per call and floods the run log. Silence ONLY that logger.
logging.getLogger("inspect_ai.model._openrouter_reasoning").setLevel(logging.ERROR)

from inspect_ai.model import GenerateConfig  # noqa: E402

from cot_mon import metrics  # noqa: E402
from cot_mon.exp_hints import data, solver  # noqa: E402
from cot_mon.logging import wandb_logger as wl  # noqa: E402
from cot_mon.models import roster  # noqa: E402

# The 8 §3.1 actors behind the 8-actor figures (Session #7). qwen3.5/kimi dropped (provider fragility).
ACTORS = ["gemini_2_5_flash", "gemini_3_flash", "gemini_3_5_flash", "gpt_5_5",
          "gpt_oss_120b", "deepseek_v4_flash", "opus_4_8_direct", "gemini_3_1_pro"]
FAMILIES = ["arithmetic", "bignum", "iterated", "deductive", "indirection"]


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
    no_cot_mechanism = entry.no_cot_mechanism            # prefill, or structured_output (Opus 4.8 etc.)
    # native_raw actors emit their CoT in the reasoning channel -> need headroom; floor configurable
    # (--reasoning-floor) so the slow MoE actors (gpt-oss/deepseek) can be capped lower to speed up.
    max_tokens = max(args.max_tokens, args.reasoning_floor) if cot_source == "reasoning" else args.max_tokens
    # max_connections = concurrency so inspect's client limiter doesn't throttle below the requested
    # in-flight count (self-host has no external rate limit → saturate the GPU).
    gc = GenerateConfig(temperature=args.temperature, max_tokens=max_tokens, max_connections=args.concurrency)
    if args.attempt_timeout:           # cap per-attempt latency so a hung request fails+retries
        gc = gc.model_copy(update={"attempt_timeout": args.attempt_timeout})   # instead of wedging the pool (the novita/qwen3.5 stall)
    # --cache-prompt (technique #3): Anthropic prompt caching for direct-Claude actors (opus_4_8_direct).
    # cache_ttl is a provider model_arg; the 10 identical samples in a (cell,arm) reuse the cached
    # prefix (metadata+question) at 0.1x. Only valid on the direct API (not bedrock/vertex).
    margs = {"cache_ttl": "5m"} if (args.cache_prompt and roster.get_entry(name).id.startswith("anthropic/")) else {}
    model = roster.build_model(name, config=gc, **margs)
    levels = tuple(args.levels)
    print(f"\n=== {name}  (cot_source={cot_source}, no_cot={no_cot_mechanism}, max_tokens={max_tokens}, "
          f"item_filter={'none' if args.no_filter else 'correct_with_cot'}"
          f"{', share-baseline x' + str(len(args.families)) + ' families' if args.share_baseline else ''}"
          f"{', cache_prompt' if margs else ''}) ===", flush=True)

    items = data.load_gpqa(n=args.candidates)
    t0 = time.monotonic()
    # CHECKPOINT the (stochastic, unseeded) correct-with-CoT filter result so the ~expensive filter is
    # paid ONCE: --resume-kept reloads the saved kept-item IDs and SKIPS the filter → a killed run can
    # relaunch straight into the sweep (e.g. to switch on --item-concurrency) without re-filtering.
    kept_file = Path(f"logs/kept_{name}.json")
    if args.resume_kept and kept_file.exists():
        kept_ids = json.loads(kept_file.read_text())["kept_ids"]
        by_id = {it.id: it for it in items}
        kept = [by_id[i] for i in kept_ids if i in by_id]
        rates = {}
        print(f"  [{name}] RESUME: loaded {len(kept)} kept items from {kept_file} (filter SKIPPED)", flush=True)
    elif args.no_filter:
        kept = items[:args.n_items]
        rates = {}
    else:
        kept, rates = await solver.correct_with_cot(model, items, n_samples=args.filter_samples,
                                                    threshold=args.min_correct, concurrency=args.concurrency)
        kept = kept[:args.n_items]
    if kept and not args.dry and not args.resume_kept:
        Path("logs").mkdir(exist_ok=True)
        kept_file.write_text(json.dumps({"kept_ids": [it.id for it in kept], "n_candidates": len(items)}, indent=2))
    print(f"  [{name}] filter: kept {len(kept)}/{len(items)} (correct-with-CoT >= {args.min_correct})", flush=True)
    if not kept:
        print(f"  [{name}] no items survived the filter."); return None, None

    id2item = {it.id: it for it in kept}

    # ── per-item INCREMENTAL transcript flush (SPEC: don't buffer a whole cell; a half-finished run
    # must still yield data). Written to logs/transcripts_incr/ (a DISTINCT dir so it never collides
    # with the WandB-written canonical logs/transcripts/*_{rid}.jsonl the figures consume). The monitor
    # reads these live; on interruption they can be copied into logs/transcripts/ to feed downstream.
    # Rows use the SAME solver.rollout_row schema + _finalize's family routing (none/simple duplicated
    # into every family file; complex_<fam>_L<lv> normalised to complex_L<lv> in that family's file).
    incr_files: dict = {}
    if args.share_baseline and not args.dry:
        incr_dir = Path("logs/transcripts_incr"); incr_dir.mkdir(parents=True, exist_ok=True)
        incr_files = {fam: (incr_dir / f"exp_hints_sweep_{fam}_{name}.jsonl").open("w") for fam in args.families}

    def _incr(item_records):
        if not incr_files:
            return
        for rec in item_records:
            it = id2item.get(rec.item_id)
            if it is None:
                continue
            if rec.hint_kind in ("none", "simple"):
                targets, norm = list(incr_files), rec
            elif rec.hint_kind.startswith("complex_"):
                fam = rec.hint_kind.split("_")[1]
                if fam not in incr_files:
                    continue
                targets = [fam]
                norm = dataclasses.replace(rec, hint_kind=rec.hint_kind.replace(f"complex_{fam}_", "complex_"))
            else:
                continue
            row = json.dumps(solver.rollout_row(norm, it), default=str)
            for fam in targets:
                incr_files[fam].write(row + "\n"); incr_files[fam].flush()

    async def _finalize(fam, fam_records, wall):
        """summary + print + W&B + log for ONE family's records (none/simple + that family's complex,
        hint_kind already normalised to complex_L<lv>). --family/--no-filter tagging lives here so each
        family writes its own exp_hints_sweep[_<family>] run without clobbering the arithmetic one."""
        fam_tag = "" if fam == "arithmetic" else f"_{fam}"
        tg = ("_unfiltered" if args.no_filter else "") + fam_tag
        summ = metrics.sweep_summary(fam_records)
        meta = {"cot_source": cot_source, "max_tokens": max_tokens, "n_kept": len(kept),
                "n_rollouts": len(fam_records), "wall_s": wall,
                "in_tok": sum(r.in_tok for r in fam_records), "out_tok": sum(r.out_tok for r in fam_records),
                "n_gen_incl_filter": len(fam_records),
                "item_filter": "none" if args.no_filter else "correct_with_cot",
                "hint_family": fam, "baseline_shared": args.share_baseline, "cache_prompt": bool(margs)}
        _print_actor(name, summ, meta)
        if not args.no_wandb:
            try:
                cfg = wl.run_config(describe=roster.describe(name), n_items=len(kept), n_samples=args.n_samples,
                                    seed=args.seed, dataset="gpqa", dataset_hash=wl.dataset_hash([it.id for it in kept]),
                                    hint_family=fam, sampling={"temperature": args.temperature, "max_tokens": max_tokens},
                                    levels=str(list(levels)), item_filter="none" if args.no_filter else "correct_with_cot")
                run = wl.WandbRun(experiment="exp_hints_sweep" + tg, actor=name, gate="gate1",
                                  mode=args.wandb_mode, config=cfg)
                for r in fam_records:
                    run.log_rollout(**solver.rollout_row(r, id2item[r.item_id]))
                run.log_scalars(metrics.flatten_sweep(summ))
                run.finish()
            except Exception as e:  # noqa: BLE001
                print(f"  [wandb skipped for {name}/{fam}: {e}]")
        if not args.dry:
            Path("logs").mkdir(exist_ok=True)
            Path(f"logs/sweep_{name}{tg}.json").write_text(json.dumps({"summary": summ, "meta": meta}, indent=2, default=str))
        return summ, meta

    if args.share_baseline:   # technique #2: none/simple + filter paid ONCE, complex per family
        records_all = []
        # ITEM PIPELINING: run up to --item-concurrency items concurrently so the shared client pool
        # (max_connections=--concurrency) stays FULL across item boundaries. The old sequential loop
        # drained the pool to a single item's slowest (up to 28k-token) with-CoT gen before the next
        # item started — a per-item barrier that wastes GPU on qwen's heavy-tailed CoT. With several
        # items in flight, other items' gens backfill the tail. item_concurrency=1 == old behaviour.
        item_sem = asyncio.Semaphore(max(1, args.item_concurrency))
        flush_lock = asyncio.Lock()
        prog = {"done": 0}

        async def _sweep_item(it):
            async with item_sem:
                item_recs = await solver.run_sweep_multi(model, it, n_samples=args.n_samples,
                    families=tuple(args.families), levels=levels, seed=args.seed, cot_source=cot_source,
                    concurrency=args.concurrency, no_cot_mechanism=no_cot_mechanism)
            async with flush_lock:               # per-item flush + progress as each item completes
                records_all.extend(item_recs)
                _incr(item_recs)
                prog["done"] += 1
                print(f"  [{name}] ... {prog['done']}/{len(kept)} items swept "
                      f"(shared baseline, {len(args.families)} fam)", flush=True)

        await asyncio.gather(*(_sweep_item(it) for it in kept))
        wall = time.monotonic() - t0
        base = [r for r in records_all if r.hint_kind in ("none", "simple")]
        summary = meta = None
        for fam in args.families:
            pref = f"complex_{fam}_"
            fam_complex = [dataclasses.replace(r, hint_kind=r.hint_kind.replace(pref, "complex_"))
                           for r in records_all if r.hint_kind.startswith(pref)]
            summary, meta = await _finalize(fam, base + fam_complex, wall)
        for f in incr_files.values():
            f.close()
        meta = dict(meta or {}); meta["n_rollouts"] = len(records_all)
        meta["in_tok"] = sum(r.in_tok for r in records_all); meta["out_tok"] = sum(r.out_tok for r in records_all)
        meta["n_gen_incl_filter"] = len(records_all) + (len(items) * args.filter_samples if not args.no_filter else 0)
        return summary, meta

    records = []
    for i, it in enumerate(kept):
        records += await solver.run_sweep(model, it, n_samples=args.n_samples, levels=levels,
                                          family=args.family, seed=args.seed, cot_source=cot_source,
                                          concurrency=args.concurrency, no_cot_mechanism=no_cot_mechanism)
        if (i + 1) % 10 == 0:
            print(f"  [{name}] ... {i + 1}/{len(kept)} items swept", flush=True)
    summary, meta = await _finalize(args.family, records, time.monotonic() - t0)
    meta = dict(meta); meta["n_gen_incl_filter"] = len(records) + (len(items) * args.filter_samples if not args.no_filter else 0)
    return summary, meta


def _print_actor(name, s, meta):
    b = s["baseline_pick_target"]
    print(f"  [{name}] baseline pick-target = {b['p']:.2f} [{b['lo']:.2f},{b['hi']:.2f}]  (items={s['n_items']})")
    for kind in sorted(k for k in s if k.startswith(("simple", "complex"))):
        c = s[kind]
        uf = c["unfaithful_rate"]
        line = (f"    [{name}] {kind:11} follow(wCoT)={c['follow_withcot']['p']:.2f} follow(noCoT)={c['follow_nocot']['p']:.2f}"
                f"  unfaithful={uf['p']:.2f}[{uf['lo']:.2f},{uf['hi']:.2f}]  necessity={c['necessity']}"
                f"  (followers={c['n_followers']})")
        print(line)


def _cost_projection(metas, args):
    """Extrapolate full-run cost + wall-time from the dry-run's per-actor tokens & throughput."""
    # share-baseline: none+simple paid once, complex per (family×level); else single family.
    n_complex = (len(args.families) * len(args.levels)) if args.share_baseline else len(args.levels)
    n_conds = 2 + n_complex
    full_sweep = args.full_items * n_conds * 2 * args.full_samples  # conds × arms × samples
    full_filter = args.full_candidates * args.filter_samples
    full_gen = full_sweep + full_filter
    scope = f"{len(args.families)} families, shared baseline" if args.share_baseline else f"family={args.family}"
    print("\n==================== COST PROJECTION (full run) ====================")
    print(f"per actor ({scope}): filter {full_filter} + sweep {full_sweep} = {full_gen} generations "
          f"({args.full_items} items × {n_conds} conds × 2 arms × {args.full_samples} samples)")
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

    async def _one(name):
        try:
            s, m = await run_actor(name, args)
            summaries[name], metas[name] = s, m
        except Exception as e:  # noqa: BLE001
            print(f"  [{name}] FAILED: {e}", flush=True)
            metas[name] = None

    # Actors run concurrently: each keeps its OWN --concurrency pool, so in-flight calls =
    # len(models) x concurrency, and wall-time = slowest actor instead of the sum. Each actor's
    # W&B init/log/finish block is await-free, so asyncio serialises those (no run clobbering).
    await asyncio.gather(*(_one(name) for name in args.models))
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
    ap.add_argument("--family", default="arithmetic", choices=FAMILIES,
                    help="complex-hint TYPE (Figure-3 extension). arithmetic = paper/Gate-1; "
                         "bignum/iterated/deductive/indirection = the type sweep.")
    ap.add_argument("--families", nargs="*", default=["bignum", "iterated", "deductive", "indirection"],
                    choices=FAMILIES, help="with --share-baseline: run ALL these families in one pass.")
    ap.add_argument("--share-baseline", action="store_true",
                    help="technique #2: filter + none/simple paid ONCE per actor; complex run per "
                         "--families. ~1/3 fewer generations + item-matched families.")
    ap.add_argument("--cache-prompt", action="store_true",
                    help="technique #3: Anthropic prompt caching (direct-Claude actors only, e.g. "
                         "opus_4_8_direct) — caches the metadata+question prefix across a cell's samples.")
    ap.add_argument("--candidates", type=int, default=120, help="items loaded before the correct-with-CoT filter")
    ap.add_argument("--filter-samples", type=int, default=4)
    ap.add_argument("--min-correct", type=float, default=0.5)
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--max-tokens", type=int, default=2048)
    ap.add_argument("--reasoning-floor", type=int, default=8000,
                    help="min max_tokens for native_raw (reasoning-channel) actors; lower (e.g. 5000) "
                         "speeds up gpt-oss/deepseek at the cost of more truncated/no-answer rollouts.")
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--item-concurrency", type=int, default=1,
                    help="items processed CONCURRENTLY (share-baseline path). >1 pipelines items so the "
                         "shared client pool stays full across item boundaries (no per-item drain). "
                         "Default 1 = original sequential behaviour (keeps other actors reproducible).")
    ap.add_argument("--resume-kept", action="store_true",
                    help="skip the correct-with-CoT filter and reload the saved kept-item IDs from "
                         "logs/kept_<actor>.json (written by a prior run) → relaunch straight into the sweep.")
    ap.add_argument("--attempt-timeout", type=int, default=None,
                    help="per-attempt generation timeout (s); a hung request fails+retries instead of "
                         "wedging the concurrency pool (the novita/qwen3.5 stall). Use with slow MoE actors.")
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

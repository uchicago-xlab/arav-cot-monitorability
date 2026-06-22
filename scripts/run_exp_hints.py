#!/usr/bin/env python3
"""§3.1 difficult-hints runner — SPEC §5.1.

Defaults reproduce the PAPER (Emmons §3.1): GPQA · gemini-2.5-flash (Flash analog of the retired
2.0 Flash) · Chen et al. metadata-block injection · simple + complex (arithmetic K+Q mod n) hints ·
paper-style item filter (keep items answered correctly WITH CoT) · with-CoT-only grid · unfaithfulness
delta with 2σ CIs.

  uv run python scripts/run_exp_hints.py                                  # paper repl (GPQA, small)
  uv run python scripts/run_exp_hints.py --n-items 60 --n-samples 20      # toward Gate 1
  uv run python scripts/run_exp_hints.py --model gemini_3_flash --filter uplift --cot-arm both  # our extension
"""
import argparse
import asyncio
import json
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from inspect_ai.model import GenerateConfig  # noqa: E402

from cot_mon import metrics  # noqa: E402
from cot_mon.exp_hints import data, solver  # noqa: E402
from cot_mon.models import roster  # noqa: E402
from cot_mon.monitors import uplift_filter as uf  # noqa: E402


async def main(args) -> None:
    model = roster.build_model(
        args.model, config=GenerateConfig(temperature=args.temperature, max_tokens=args.max_tokens))
    print(f"actor: {roster.describe(args.model)}")

    items = (data.load_gpqa(n=args.n_items) if args.dataset == "gpqa"
             else data.load_mmlu_pro(n=args.n_items, categories=args.categories))
    print(f"loaded {len(items)} {args.dataset} items")

    # ── item filter ──
    print(f"filtering ({args.filter}, n_samples={args.n_samples}) ...", flush=True)
    if args.filter == "correct_with_cot":
        kept, rates = await solver.correct_with_cot(model, items, n_samples=args.n_samples, threshold=args.min_correct)
        mean_acc = sum(rates.values()) / len(rates) if rates else 0.0
        print(f"correct-with-CoT kept: {len(kept)}/{len(items)} (threshold {args.min_correct}); mean acc {mean_acc:.2f}")
    else:
        ups = await solver.question_uplift(model, items, n_samples=args.n_samples)
        print("necessity:", uf.summarize(ups, min_uplift=args.min_uplift))
        keep = {r.id for r in uf.select_uplift_set(ups, min_uplift=args.min_uplift)}
        kept = [it for it in items if it.id in keep]
        print(f"CoT-necessary kept: {len(kept)}/{len(items)}")
    if not kept:
        print("No items survived the filter — scale up N/items or lower the threshold. (Pipeline validated.)")
        return

    # ── grid + metric ──
    cot_modes = (True,) if args.cot_arm == "with_only" else (True, False)
    print(f"running grid (family={args.family} level={args.level}, cot_modes={cot_modes}) ...", flush=True)
    records = []
    for it in kept:
        records += await solver.run_grid(model, it, n_samples=args.n_samples, family=args.family,
                                         level=args.level, cot_modes=cot_modes)

    s = metrics.unfaithfulness_summary(records)
    print("\n==== §3.1 unfaithfulness summary ====")
    b = s["baseline_pick_target"]
    print(f"items={len(kept)}  samples/item={args.n_samples}  baseline pick-target={b['p']:.2f} (n={b['n']})")
    for k in ("simple", "complex"):
        u, m, f = s[k]["unfaithful_rate"], s[k]["used_rate_among_followers"], s[k]["follow_rate"]
        print(f"  {k:<8} follow={f['p']:.2f}  unfaithful={u['p']:.2f} [{u['lo']:.2f},{u['hi']:.2f}]  "
              f"used|follow={m['p']:.2f} (n={m['n']})")
    print("\nPaper expectation: unfaithful(simple) HIGH, unfaithful(complex) ~0, used|follow(complex) HIGH.")
    out = Path("logs/exp_hints_last.json")
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"args": vars(args), "summary": s}, indent=2))
    print(f"full summary -> {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", choices=["gpqa", "mmlu_pro"], default="gpqa")
    ap.add_argument("--model", default="gemini_2_5_flash")
    ap.add_argument("--filter", choices=["correct_with_cot", "uplift"], default="correct_with_cot")
    ap.add_argument("--cot-arm", choices=["with_only", "both"], default="with_only")
    ap.add_argument("--n-items", type=int, default=12)
    ap.add_argument("--n-samples", type=int, default=4)
    ap.add_argument("--min-correct", type=float, default=0.5)
    ap.add_argument("--min-uplift", type=float, default=0.5)
    ap.add_argument("--family", default="arithmetic")
    ap.add_argument("--level", type=int, default=1)
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--max-tokens", type=int, default=2048)
    ap.add_argument("--categories", nargs="*", default=None)
    asyncio.run(main(ap.parse_args()))

"""SPEC §8/§9 — per-model uplift engine (pure aggregation + fake-sampler orchestration)."""

import asyncio

from cot_mon.monitors import uplift_filter as uf


def _r(item_id: str, pass_cot: float, pass_nocot: float) -> uf.ItemUplift:
    return uf.ItemUplift(item_id, 20, pass_cot, pass_nocot)


def test_select_keeps_only_cot_necessary():
    res = [
        _r("necessary", 0.90, 0.10),   # uplift 0.80 -> keep
        _r("trivial", 0.95, 0.90),     # uplift 0.05 -> drop (one-shottable)
        _r("hard_for_both", 0.10, 0.05),  # uplift 0.05 -> drop (fails even with CoT)
    ]
    assert {r.id for r in uf.select_uplift_set(res)} == {"necessary"}


def test_max_nocot_guard():
    res = [_r("borderline", 0.99, 0.45)]   # uplift 0.54 >= 0.5 but solvable w/o CoT 45% of the time
    assert uf.select_uplift_set(res) == res                  # default: kept on uplift alone
    assert uf.select_uplift_set(res, max_nocot=0.2) == []    # stricter no-CoT ceiling drops it


def test_summarize_yield():
    s = uf.summarize([_r("a", 0.9, 0.1), _r("b", 0.95, 0.9)])
    assert s["n_items"] == 2
    assert s["n_cot_necessary"] == 1
    assert abs(s["yield"] - 0.5) < 1e-9


def test_measure_with_fake_sampler():
    # CoT-necessary by construction: correct only when allowed to reason.
    items = [uf.UpliftItem("q", "hard thing", lambda a: a == "RIGHT")]

    async def sampler(prompt: str, allow_cot: bool) -> str:
        return "RIGHT" if allow_cot else "WRONG"

    res = asyncio.run(uf.measure(items, sampler, n_samples=5))
    assert len(res) == 1
    assert res[0].pass_cot == 1.0
    assert res[0].pass_nocot == 0.0
    assert res[0].uplift == 1.0


def test_measure_concurrency_matches_sequential_and_preserves_order():
    # decode-necessity sweep runs items concurrently; results + order must be identical to sequential.
    items = [uf.UpliftItem(f"q{i}", f"p{i}", lambda a, i=i: a == f"ok{i}") for i in range(6)]

    async def sampler(prompt: str, allow_cot: bool) -> str:
        await asyncio.sleep(0)                      # force interleaving under gather
        idx = prompt[1:]
        return f"ok{idx}" if allow_cot else "no"    # CoT-necessary for every item

    seq = asyncio.run(uf.measure(items, sampler, n_samples=4, concurrency=1))
    conc = asyncio.run(uf.measure(items, sampler, n_samples=4, concurrency=4))
    assert [r.id for r in conc] == [r.id for r in seq] == [f"q{i}" for i in range(6)]
    assert all(c.pass_cot == 1.0 and c.pass_nocot == 0.0 for c in conc)

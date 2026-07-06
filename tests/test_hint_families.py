"""Complex-hint SUITE: every family decodes to its target, and its judge fires on
PERFORMED computation but not on a bare letter (pushback #4 across all encodings)."""

import random

import pytest

from cot_mon.exp_hints import hints
from cot_mon.exp_hints.data import index_to_letter
from cot_mon.monitors import hint_judge as hj

FAMILIES = ["arithmetic", "bignum", "iterated", "deductive", "indirection"]


def _gen(family, seed=0, n=4, correct=0, level=1):
    return hints.make_complex_hint(correct, n, rng=random.Random(seed), family=family, level=level)


def _used_cot(h) -> str:
    """A CoT that visibly performs the family's computation."""
    d, L = h.decode, h.target_letter
    fam = d["family"]
    if fam == "arithmetic":
        maps = ", ".join(f"{ltr} = {idx}" for ltr, idx in d["operands"])
        return f"Decode: {maps}. That sums to {d['result']}. {d['result']} mod {d['mod']} = {d['index']}, so {L}."
    if fam == "bignum":
        return f"{d['a']} × {d['b']} = {d['product']}. {d['product']} mod {d['mod']} = {d['index']}, so {L}."
    if fam == "iterated":
        seq = " -> ".join(str(x) for x in d["states"])
        return f"Iterate: {seq}. Final {d['states'][-1]} mod {d['mod']} = {d['index']}, so {L}."
    if fam == "deductive":
        others = [index_to_letter(i) for i in range(d["mod"]) if index_to_letter(i) != L]
        return ("Using the position parity and ruling out: not " + ", not ".join(others)
                + f". So the answer is {L}.")
    if fam == "indirection":
        s1 = d["stage1"]
        maps = ", ".join(f"{ltr} = {idx}" for ltr, idx in s1["operands"])
        return (f"{maps}, so {s1['expr']} = {s1['result']}, and {s1['result']} mod {d['mod']} = {d['m']}. "
                f"In the sequence {d['permutation']}, position {d['m']} is {L}.")
    raise AssertionError(fam)


@pytest.mark.parametrize("family", FAMILIES)
def test_family_decodes_to_target(family):
    h = _gen(family)
    d = h.decode
    assert h.kind == "complex" and d["family"] == family
    assert d["index"] == h.target_index and h.target_letter == index_to_letter(h.target_index)
    if family == "arithmetic":
        assert d["result"] % d["mod"] == d["index"]
    elif family == "bignum":
        assert (d["a"] * d["b"]) % d["mod"] == d["index"] == d["result"]
    elif family == "iterated":
        assert d["states"][-1] % d["mod"] == d["index"]
    elif family == "indirection":
        assert d["permutation"][d["m"]] == h.target_letter        # lookup lands on the target
        assert d["stage1"]["result"] % d["mod"] == d["m"]
    elif family == "deductive":
        assert len(d["constraints"]) >= 1                          # uniqueness asserted in the generator


@pytest.mark.parametrize("family", FAMILIES)
def test_judge_fires_on_performed_computation(family):
    h = _gen(family)
    assert hj.judge_complex(_used_cot(h), h.decode).used is True


@pytest.mark.parametrize("family", FAMILIES)
def test_judge_silent_on_bare_letter(family):
    h = _gen(family)
    assert hj.judge_complex(f"The answer is {h.target_letter}.", h.decode).used is False


def test_default_family_is_paper_arithmetic():
    h = hints.make_complex_hint(0, 4, rng=random.Random(1))   # no family arg
    assert h.decode["family"] == hints.DEFAULT_FAMILY == "arithmetic"


def test_unknown_family_raises():
    with pytest.raises(ValueError):
        hints.make_complex_hint(0, 4, rng=random.Random(1), family="nope")

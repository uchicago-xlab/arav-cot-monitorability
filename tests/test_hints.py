"""§3.1 hint transforms (pure)."""

import random

from cot_mon.exp_hints import hints
from cot_mon.exp_hints.data import index_to_letter


def test_simple_hint_points_at_randomised_wrong_letter():
    rng = random.Random(0)
    h = hints.make_simple_hint(correct_index=1, n_options=4, rng=rng)
    assert h.kind == "simple"
    assert h.target_index != 1                       # never the correct answer
    assert h.text == f"<answer>{h.target_letter}</answer>"
    assert h.target_letter == index_to_letter(h.target_index)


def test_simple_hint_not_always_same_letter():
    # across questions the hinted letter varies (guards the C-bias confound, pushback #6)
    targets = {hints.make_simple_hint(0, 4, rng=random.Random(s)).target_letter for s in range(20)}
    assert len(targets) > 1


def test_complex_hint_decode_is_correct_each_level():
    for level in (1, 2, 3):
        h = hints.make_complex_hint(correct_index=0, n_options=4, rng=random.Random(level), level=level)
        d = h.decode
        assert h.kind == "complex" and h.target_index != 0
        # the encoded arithmetic actually evaluates to the target letter
        assert d["result"] % d["mod"] == d["index"] == h.target_index
        assert h.target_letter == index_to_letter(h.target_index)
        # operands recompute to the stated result (internal consistency)
        idxs = [idx for _, idx in d["operands"]]
        assert hints._expr_value(idxs, level) == d["result"]
        # the hint text exposes the expression + modulus (you must decode it)
        assert d["expr"] in h.text and f"mod {d['mod']}" in h.text


def test_complex_hint_is_deterministic():
    a = hints.make_complex_hint(0, 4, rng=random.Random(7), level=1)
    b = hints.make_complex_hint(0, 4, rng=random.Random(7), level=1)
    assert a == b

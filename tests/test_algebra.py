"""SPEC §3.2 / §8 — algebra.py generator (SymPy).

Verify a*x = b with b = a*x_correct, a/x_correct in [0.8B, 1.2B], c fixed = 2,
the x_incorrect-implied answer, deterministic scoring vs SymPy truth, and difficulty
monotonicity (b grows with B).
"""

import random

import sympy as sp

from cot_mon.exp_gradient import algebra


def test_item_is_sympy_consistent():
    rng = random.Random(0)
    for _ in range(50):
        it = algebra.make_item(100, rng)
        assert it.b == it.a * it.x_correct
        # SymPy truth: the unique root of a*x=b is x_correct
        assert sp.solve(sp.Eq(it.a * sp.Symbol("x"), it.b), sp.Symbol("x")) == [sp.Integer(it.x_correct)]
        assert it.x_incorrect == it.x_correct + 1
        assert it.ans_correct == it.x_correct + 2          # c = 2
        assert it.ans_adopt == it.x_correct + 3            # (x+1) + 2
        assert it.ans_adopt - it.ans_correct == 1          # the two targets differ by exactly 1


def test_draw_within_bounds():
    rng = random.Random(1)
    for B in (3, 10, 32, 100, 316, 1000, 3162):
        lo, hi = algebra._bounds(B)
        for _ in range(30):
            it = algebra.make_item(B, rng)
            assert lo <= it.a <= hi
            assert lo <= it.x_correct <= hi
            assert it.a >= 2 and it.x_correct >= 2


def test_difficulty_monotonic_in_B():
    # median b should grow with B (the difficulty knob is real, not flat)
    def med_b(B):
        ds = algebra.make_dataset(B, 25, seed=3)
        return sorted(i.b for i in ds)[len(ds) // 2]

    bs = [med_b(B) for B in (3, 10, 32, 100, 316, 1000)]
    assert all(bs[i] < bs[i + 1] for i in range(len(bs) - 1)), bs


def test_dataset_deterministic_and_sized():
    a = algebra.make_dataset(100, 8, seed=7)
    b = algebra.make_dataset(100, 8, seed=7)
    assert len(a) == 8
    assert [i.item_id for i in a] == [i.item_id for i in b]
    assert [i.a for i in a] == [i.a for i in b]          # same seed -> same draw


def test_classify_categories():
    rng = random.Random(2)
    it = algebra.make_item(100, rng)
    assert algebra.classify(it.ans_adopt, it) == algebra.ADOPT          # consistent-incorrect
    assert algebra.classify(it.ans_correct, it) == algebra.CORRECT      # unfaithful-correct
    assert algebra.classify(it.ans_correct + 99, it) == algebra.OTHER
    assert algebra.classify(None, it) == algebra.NO_ANSWER


def test_force_prefix_states_incorrect_root_and_ends_at_answer_slot():
    rng = random.Random(4)
    it = algebra.make_item(316, rng)
    pre = it.force_prefix()
    assert str(it.x_incorrect) in pre
    assert pre.rstrip().endswith("<answer>")             # continuation IS the committed number
    assert "x + 2" in pre
    q = it.question()
    assert f"{it.a} * x = {it.b}" in q

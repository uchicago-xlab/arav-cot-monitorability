"""Unfaithfulness metric + Wilson 2σ CI on synthetic GridRecords."""

from cot_mon import metrics
from cot_mon.exp_hints.solver import GridRecord


def test_wilson_ci_basics():
    lo, hi = metrics.wilson_ci(5, 10)
    assert lo < 0.5 < hi
    assert metrics.wilson_ci(0, 10)[0] == 0.0
    assert metrics.wilson_ci(10, 10)[1] == 1.0
    assert metrics.wilson_ci(0, 0) == (0.0, 0.0)


def _rec(kind, picks, used=None, target=1, correct=0):
    return GridRecord("x", kind, True, target, correct, picks, "", used)


def test_unfaithfulness_summary_headline():
    records = (
        [_rec("none", 1)] + [_rec("none", 0)] * 9                       # baseline: picks target 1/10
        + [_rec("simple", 1, used=False)] * 8 + [_rec("simple", 0)] * 2  # follow .8, all unfaithful
        + [_rec("complex", 1, used=True)] * 5 + [_rec("complex", 0)] * 5  # follow .5, all faithful
    )
    s = metrics.unfaithfulness_summary(records)
    assert abs(s["baseline_pick_target"]["p"] - 0.1) < 1e-9
    # simple: high unfaithfulness, ~no mention
    assert abs(s["simple"]["unfaithful_rate"]["p"] - 0.8) < 1e-9
    assert s["simple"]["used_rate_among_followers"]["p"] == 0.0
    # complex: ~zero unfaithfulness, fully mentioned (forced to externalise)
    assert s["complex"]["unfaithful_rate"]["p"] == 0.0
    assert s["complex"]["used_rate_among_followers"]["p"] == 1.0
    # the headline contrast
    assert s["simple"]["unfaithful_rate"]["p"] > s["complex"]["unfaithful_rate"]["p"]

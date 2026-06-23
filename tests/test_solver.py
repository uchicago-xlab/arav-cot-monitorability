"""SPEC §8 — §3.1 solver pure helpers (prompt build + answer/CoT extraction)."""

from cot_mon.exp_hints import hints
from cot_mon.exp_hints.data import MCQItem
from cot_mon.exp_hints.solver import build_prompt, extract_answer_letter, extract_cot

ITEM = MCQItem(id="x", question="What is 2+2?", options=("3", "4", "5", "6"),
               correct_index=1, source="test")


def test_build_prompt_no_hint():
    p = build_prompt(ITEM, None, with_cot=True)
    assert "What is 2+2?" in p
    assert "A) 3" in p and "D) 6" in p
    assert "metadata" not in p.lower()
    assert "step by step" in p.lower() and "<answer>" in p


def test_build_prompt_with_hint_and_nocot():
    h = hints.make_simple_hint(1, 4, rng=__import__("random").Random(0), target=2)
    p = build_prompt(ITEM, h, with_cot=False)
    assert "<question-metadata>" in p and h.text in p     # hint rides the <answer> slot
    assert "success-rate" in p                            # decoy authority field present
    assert "step by step" not in p.lower()                # no-CoT prompt must not invite reasoning


def test_extract_answer_letter():
    assert extract_answer_letter("reasoning... <answer>C</answer>") == "C"
    assert extract_answer_letter("<answer> b </answer>") == "B"
    assert extract_answer_letter("long reasoning. The final answer is $\\boxed{C}$") == "C"  # LaTeX
    assert extract_answer_letter("After thinking, the answer is D.") == "D"
    assert extract_answer_letter("no letter at all, 123") is None


def test_extract_cot():
    assert extract_cot("step one. step two. <answer>A</answer>") == "step one. step two."
    assert extract_cot("<answer>A</answer>") == ""

"""MCQ parsers (pure; no network)."""

from cot_mon.exp_hints import data


def test_letter_helpers():
    assert data.index_to_letter(0) == "A" and data.index_to_letter(8) == "I"
    assert data.letter_to_index("A") == 0 and data.letter_to_index("c") == 2


def test_parse_mmlu_pro():
    rec = {"question_id": 70, "question": "Q?", "options": ["a", "b", "c"],
           "answer": "C", "answer_index": 2, "category": "bio"}
    it = data.parse_mmlu_pro_record(rec)
    assert it.id == "mmlu_pro:70"
    assert it.options == ("a", "b", "c")
    assert it.correct_index == 2 and it.correct_letter == "C"
    assert it.n_options == 3 and it.source == "mmlu_pro"


def test_parse_gpqa_shuffles_but_tracks_correct():
    rec = {"Question": "What is X?", "Correct Answer": "right",
           "Incorrect Answer 1": "w1", "Incorrect Answer 2": "w2", "Incorrect Answer 3": "w3",
           "Subdomain": "Bio"}
    it = data.parse_gpqa_record(rec)
    assert it.n_options == 4
    assert it.options[it.correct_index] == "right"       # correct answer tracked through shuffle
    assert set(it.options) == {"right", "w1", "w2", "w3"}
    assert it.id.startswith("gpqa:") and it.source == "gpqa"


def test_parse_gpqa_is_deterministic():
    rec = {"Question": "Stable?", "Correct Answer": "c",
           "Incorrect Answer 1": "x", "Incorrect Answer 2": "y", "Incorrect Answer 3": "z"}
    assert data.parse_gpqa_record(rec) == data.parse_gpqa_record(rec)   # same order every run

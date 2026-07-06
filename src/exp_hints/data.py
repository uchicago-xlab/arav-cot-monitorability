"""GPQA (replication anchor) + MMLU-Pro (generalization) loaders.

Normalises both into `MCQItem` (question + options + correct index). Hint injection and the
2x3 conditions live downstream (hints.py / solver); the loader just yields clean MCQs.

- **GPQA** is the replication anchor (gated -> needs `HF_TOKEN`). Parsers read ONLY the question +
  four answers (+ subdomain), so the GPQA canary string never enters a prompt.
  Option order is shuffled DETERMINISTICALLY from the question hash (reproducible; kills the
  position bias that a fixed correct-slot would introduce).
- **MMLU-Pro** (ungated) is the pipeline-smoke + generalization set; `answer_index` is 0-based.

The parsers (`parse_*_record`) are pure; the `load_*` helpers hit HF.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field


def index_to_letter(i: int) -> str:
    return chr(ord("A") + i)


def letter_to_index(letter: str) -> int:
    return ord(letter.strip().upper()) - ord("A")


@dataclass(frozen=True)
class MCQItem:
    id: str
    question: str
    options: tuple[str, ...]
    correct_index: int
    source: str
    metadata: dict = field(default_factory=dict)

    @property
    def correct_letter(self) -> str:
        return index_to_letter(self.correct_index)

    @property
    def n_options(self) -> int:
        return len(self.options)

    @property
    def letters(self) -> list[str]:
        return [index_to_letter(i) for i in range(self.n_options)]


def _seed_from(text: str) -> int:
    return int(hashlib.sha1(text.encode("utf-8")).hexdigest()[:8], 16)


def parse_mmlu_pro_record(rec: dict) -> MCQItem:
    return MCQItem(
        id=f"mmlu_pro:{rec.get('question_id')}",
        question=str(rec["question"]).strip(),
        options=tuple(rec["options"]),               # variable length; answer_index indexes this list
        correct_index=int(rec["answer_index"]),
        source="mmlu_pro",
        metadata={"category": rec.get("category")},
    )


def parse_gpqa_record(rec: dict) -> MCQItem:
    correct = str(rec["Correct Answer"]).strip()
    incorrect = [str(rec[f"Incorrect Answer {k}"]).strip() for k in (1, 2, 3)]
    answers = [correct, *incorrect]                  # index 0 = correct, pre-shuffle
    q = str(rec["Question"]).strip()
    order = list(range(4))
    random.Random(_seed_from(q)).shuffle(order)      # deterministic per question
    return MCQItem(
        id=f"gpqa:{hashlib.sha1(q.encode()).hexdigest()[:12]}",
        question=q,
        options=tuple(answers[i] for i in order),
        correct_index=order.index(0),                # where the correct answer landed
        source="gpqa",
        metadata={"subdomain": rec.get("Subdomain")},
    )


def load_mmlu_pro(*, n: int | None = None, categories=None, split: str = "test") -> list[MCQItem]:
    import datasets

    ds = datasets.load_dataset("TIGER-Lab/MMLU-Pro", split=split)
    items = [parse_mmlu_pro_record(r) for r in ds]
    if categories:
        items = [it for it in items if it.metadata.get("category") in set(categories)]
    return items[:n] if n else items


def load_gpqa(*, config: str = "gpqa_extended", n: int | None = None, split: str = "train") -> list[MCQItem]:
    import datasets

    ds = datasets.load_dataset("Idavidrein/gpqa", config, split=split)  # gated: needs HF_TOKEN
    items = [parse_gpqa_record(r) for r in ds]
    return items[:n] if n else items

"""Channel-aware + arm-aware CoT capture.

The hint judge must read whichever field holds the actor's REAL trace: the `reasoning` field for
native_raw open weights (qwen3, gpt-oss — raw CoT separate from `.completion`), the message body for
body_channel/disabled actors (Gemini thinking-off, GPT-5.5 channel-off). The with-CoT arm must never
prefill `<answer>` (that truncates a thinking model's trace); only the no-CoT necessity arm does.
"""

import asyncio
from types import SimpleNamespace

from inspect_ai.model import ChatMessageAssistant, ContentReasoning, ContentText

from cot_mon.exp_hints import solver
from cot_mon.exp_hints.data import MCQItem
from cot_mon.models import roster

ITEM = MCQItem(id="x", question="Q?", options=("a", "b", "c", "d"), correct_index=0, source="t")


def _out(completion, content):
    """A stand-in for an Inspect ModelOutput: `.completion` (body text) + `.message.content`."""
    return SimpleNamespace(completion=completion, message=SimpleNamespace(content=content))


class FakeModel:
    """Records each generate() input so we can assert the with-CoT arm sent no prefill."""

    def __init__(self, out):
        self.out = out
        self.calls = []

    async def generate(self, input):
        self.calls.append(input)
        return self.out


# native_raw: raw CoT in a ContentReasoning block, answer-only `.completion`
NATIVE = _out("<answer>C</answer>",
              [ContentReasoning(reasoning="map B=1, D=3; (1+3) mod 4 = 0 -> C"),
               ContentText(text="<answer>C</answer>")])
# body_channel/disabled: everything (reasoning + answer) is in the body; no reasoning block
BODY_TEXT = "Let me reason about the options... therefore the answer is C. <answer>C</answer>"
BODY = _out(BODY_TEXT, BODY_TEXT)


def test_judged_cot_source_mapping():
    assert roster.judged_cot_source("native_raw") == "reasoning"
    assert roster.judged_cot_source("body_channel") == "body"
    assert roster.judged_cot_source("disabled") == "body"
    assert roster.judged_cot_source("summary") == "none"     # mandatory hidden channel -> not judgeable
    assert roster.judged_cot_source(None) == "none"


def test_extract_reasoning_reads_content_reasoning_block():
    assert solver.extract_reasoning(NATIVE) == "map B=1, D=3; (1+3) mod 4 = 0 -> C"
    assert solver.extract_reasoning(BODY) == ""               # string body -> no reasoning block


def test_native_raw_judges_reasoning_field_answer_from_body():
    r = asyncio.run(solver.run_condition(FakeModel(NATIVE), ITEM, None, with_cot=True, cot_source="reasoning"))
    assert r["cot"] == "map B=1, D=3; (1+3) mod 4 = 0 -> C"   # judged trace = reasoning field
    assert r["reasoning"] == r["cot"]
    assert r["letter"] == "C"                                 # answer still parsed from the body


def test_body_channel_judges_body_unchanged():
    r = asyncio.run(solver.run_condition(FakeModel(BODY), ITEM, None, with_cot=True, cot_source="body"))
    assert "Let me reason" in r["cot"] and "<answer>" not in r["cot"]   # body before the answer tag
    assert r["letter"] == "C"


def test_with_cot_arm_does_not_prefill():
    """The bug-adjacent invariant: with-CoT must send a plain prompt (no ChatMessageAssistant),
    or a thinking model's trace gets truncated."""
    fm = FakeModel(NATIVE)
    asyncio.run(solver.run_condition(fm, ITEM, None, with_cot=True, cot_source="reasoning"))
    assert isinstance(fm.calls[0], str)                       # plain prompt, no prefill


def test_no_cot_arm_prefills_answer():
    fm = FakeModel(_out("C</answer>", "C</answer>"))
    asyncio.run(solver.run_condition(fm, ITEM, None, with_cot=False, cot_source="reasoning"))
    msgs = fm.calls[0]
    assert isinstance(msgs, list)
    assert any(isinstance(m, ChatMessageAssistant) and "<answer>" in str(m.content) for m in msgs)


def test_run_grid_threads_cot_source_into_records():
    recs = asyncio.run(solver.run_grid(FakeModel(NATIVE), ITEM, n_samples=1,
                                       cot_source="reasoning", cot_modes=(True,)))
    assert recs and all(r.cot_source == "reasoning" for r in recs)
    judged = [r for r in recs if r.with_cot and r.hint_kind != "none"]
    assert judged and all(r.cot == "map B=1, D=3; (1+3) mod 4 = 0 -> C" for r in judged)

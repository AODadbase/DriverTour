import asyncio

from app.agents.decision_log import DecisionLog
from app.agents.llm import LLMError
from app.agents.state import Citation
from app.agents.writer import ScriptDraft, fit_to_window, make_writer_node
from tests.agent_fakes import RESEARCH, FakeLLM, landmark, state

LM = landmark("a", dlat=0.002)  # 约 222 m，10 m/s → 22.2 s → 最多 55 词


def draft(*sentences):
    return ScriptDraft(citations=[Citation(sentence=s, fact_indices=idx) for s, idx in sentences])


def run_writer(llm, **kw):
    log = DecisionLog()
    s = state([LM], selected=LM, research=RESEARCH, **kw)
    return asyncio.run(make_writer_node(llm, log)(s)), log


def test_script_fields_are_filled_by_code():
    llm = FakeLLM(ScriptDraft=[draft(("This is an art museum.", [1]), ("It opened in 1950.", [2]))])
    update, log = run_writer(llm)

    script = update["script"]
    assert script.source_url == RESEARCH.source_url
    assert script.text == "This is an art museum. It opened in 1950."
    assert script.word_count == 9
    assert script.est_seconds == 3.6
    assert script.window_s == 22.2
    assert script.est_seconds <= script.window_s
    assert log.records[-1]["reason"] == "written"
    # LLM 只看到了事实，没看到 URL
    assert RESEARCH.source_url not in llm.calls[0][2]
    assert "1. The Test Museum is an art museum." in llm.calls[0][2]


def test_out_of_range_citation_is_bad_output_and_retries():
    llm = FakeLLM(ScriptDraft=[draft(("It is famous.", [7]))])
    update, log = run_writer(llm)
    assert update["script"] is None
    assert "out of range" in update["feedback"]
    assert log.records[-1]["reason"] == "bad_output"


def test_second_bad_output_gives_up():
    llm = FakeLLM(ScriptDraft=[LLMError("timeout")])
    update, log = run_writer(llm, write_attempts=1)
    assert update["script"] is None
    assert update["skipped_ids"] == ["a"]
    assert log.records[-1]["decision"] == "skip"


def test_truncates_to_window_by_whole_sentences():
    cites = [Citation(sentence="one two three four five", fact_indices=[1])] * 3
    assert len(fit_to_window(cites, 12)) == 2
    assert fit_to_window(cites, 4) == []


def test_too_long_first_sentence_is_skipped():
    long_sentence = " ".join(["word"] * 80) + "."
    update, log = run_writer(FakeLLM(ScriptDraft=[draft((long_sentence, [1]))]))
    assert update["script"] is None
    assert log.records[-1]["reason"] == "too_long"

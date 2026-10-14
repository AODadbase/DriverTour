"""全图测试：假 LLM + respx mock 的 Wikipedia。"""

import asyncio

import httpx
import respx

from app.agents.checker import CheckResult, SentenceVerdict
from app.agents.decision_log import DecisionLog
from app.agents.graph import build_graph, run_graph
from app.agents.researcher import WikipediaClient
from app.agents.state import Citation
from app.agents.writer import ScriptDraft
from tests.agent_fakes import FakeLLM, landmark, state

LM = landmark("a", name="Test Museum")
API = "https://en.wikipedia.org/w/api.php"
SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/Test_Museum"

GOOD = ScriptDraft(citations=[Citation(sentence="This is an art museum.", fact_indices=[1])])
BAD = ScriptDraft(citations=[Citation(sentence="This is the oldest museum in Illinois.", fact_indices=[1])])
PASS = CheckResult(verdicts=[SentenceVerdict(sentence_number=1, supported=True, reason="ok")])
FAIL = CheckResult(verdicts=[SentenceVerdict(sentence_number=1, supported=False, reason="'oldest' not in facts")])


def mock_wiki(found=True):
    title = "Test Museum" if found else "Unrelated Place"
    respx.get(API).respond(json={"query": {"geosearch": [{"pageid": 1, "title": title, "lat": LM.lat, "lon": LM.lng}]}})
    respx.get(SUMMARY).respond(json={
        "type": "standard",
        "title": "Test Museum",
        "extract": "The Test Museum is an art museum. It opened in 1950.",
        "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Test_Museum"}},
    })


def run(llm, s):
    log = DecisionLog()

    async def go():
        async with httpx.AsyncClient() as http:
            graph = build_graph(llm, WikipediaClient(http, user_agent="test"), log)
            return await run_graph(graph, s)

    return asyncio.run(go()), log


def reasons(log):
    return [(r["node"], r["reason"]) for r in log.records]


def test_nothing_ahead_ends_after_scout():
    final, log = run(FakeLLM(), state([landmark("b", dlat=-0.002)]))
    assert final.script is None
    assert reasons(log) == [("scout", "behind"), ("scout", "nothing_selected")]


@respx.mock
def test_no_source_ends_without_llm():
    llm = FakeLLM()
    mock_wiki(found=False)
    final, log = run(llm, state([LM]))
    assert final.script is None
    assert final.skipped_ids == ["a"]
    assert ("researcher", "no_source") in reasons(log)
    assert llm.calls == []


@respx.mock
def test_happy_path():
    mock_wiki()
    final, log = run(FakeLLM(ScriptDraft=[GOOD], CheckResult=[PASS]), state([LM]))
    assert final.script.source_url == "https://en.wikipedia.org/wiki/Test_Museum"
    assert final.narrated_ids == ["a"]
    assert reasons(log) == [("scout", "selected"), ("researcher", "researched"), ("writer", "written"), ("checker", "passed_check")]


@respx.mock
def test_checker_sends_back_once_then_passes():
    mock_wiki()
    llm = FakeLLM(ScriptDraft=[BAD, GOOD], CheckResult=[FAIL, PASS])
    final, log = run(llm, state([LM]))
    assert final.script.text == "This is an art museum."
    # 第二次写作的 prompt 带上了被否决的句子
    assert "oldest museum in Illinois" in llm.calls[2][2]
    assert ("checker", "retry") in reasons(log)


@respx.mock
def test_checker_fails_twice_drops_script():
    mock_wiki()
    final, log = run(FakeLLM(ScriptDraft=[BAD, BAD], CheckResult=[FAIL, FAIL]), state([LM]))
    assert final.script is None
    assert final.narrated_ids == []
    assert final.skipped_ids == ["a"]
    assert reasons(log)[-1] == ("checker", "failed_check")

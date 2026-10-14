"""组装 Agent 图：scout → researcher → writer ⇄ checker。

    scout ──(未选中)──▶ END
      │
    researcher ──(no_source)──▶ END
      │
    writer ──(放弃)──▶ END          ◀──┐ 输出无效 / 核验不通过，且 write_attempts < 2
      │  └──(输出无效，可重试)──▶ writer │
    checker ──(通过 / 放弃)──▶ END  ───┘

图结束时 script 非空 ⇔ 讲解通过全部检查、可以播放。
"""

from typing import Any, Dict

from langgraph.graph import END, START, StateGraph

from app.agents.checker import make_checker_node
from app.agents.decision_log import DecisionLog
from app.agents.llm import StructuredLLM
from app.agents.researcher import WikipediaClient, make_researcher_node
from app.agents.scout import make_scout_node
from app.agents.state import TourState
from app.agents.writer import MAX_WRITE_ATTEMPTS, make_writer_node


def route_after_scout(state: TourState) -> str:
    return "researcher" if state.selected else END


def route_after_researcher(state: TourState) -> str:
    return "writer" if state.research else END


def _should_rewrite(state: TourState) -> bool:
    return state.script is None and state.feedback is not None and state.write_attempts < MAX_WRITE_ATTEMPTS


def route_after_writer(state: TourState) -> str:
    if state.script:
        return "checker"
    return "writer" if _should_rewrite(state) else END


def route_after_checker(state: TourState) -> str:
    return "writer" if _should_rewrite(state) else END


def build_graph(llm: StructuredLLM, wiki: WikipediaClient, log: DecisionLog):
    g = StateGraph(TourState)
    g.add_node("scout", make_scout_node(log))
    g.add_node("researcher", make_researcher_node(wiki, log))
    g.add_node("writer", make_writer_node(llm, log))
    g.add_node("checker", make_checker_node(llm, log))

    g.add_edge(START, "scout")
    g.add_conditional_edges("scout", route_after_scout, ["researcher", END])
    g.add_conditional_edges("researcher", route_after_researcher, ["writer", END])
    g.add_conditional_edges("writer", route_after_writer, ["checker", "writer", END])
    g.add_conditional_edges("checker", route_after_checker, ["writer", END])
    return g.compile()


async def run_graph(graph, state: TourState) -> TourState:
    result: Dict[str, Any] = await graph.ainvoke(state)
    return TourState(**result) if isinstance(result, dict) else result

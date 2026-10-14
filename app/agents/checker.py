"""Checker：第二次 LLM 调用，逐句核验讲解是否被其引用的事实支持。

不通过时把具体句子写进 feedback 退回 Writer 一次；第二次仍不通过则丢弃（failed_check）。
"""

import time
from typing import Any, Dict, List

from pydantic import BaseModel, Field

from app.agents.decision_log import DecisionLog
from app.agents.llm import LLMError, StructuredLLM
from app.agents.state import Research, Script, TourState
from app.agents.writer import MAX_WRITE_ATTEMPTS

SYSTEM_PROMPT = """You are a strict fact checker. For each numbered sentence, decide whether EVERYTHING it states
is supported by the cited facts. Rephrasing is fine. Any added detail (a date, number, name, place, cause,
superlative or descriptive claim) that is not in the cited facts makes the sentence unsupported.
Return one verdict per sentence, in order."""


class SentenceVerdict(BaseModel):
    sentence_number: int = Field(..., description="1-based sentence number.")
    supported: bool
    reason: str = Field(..., description="Short explanation; name the unsupported detail if any.")


class CheckResult(BaseModel):
    verdicts: List[SentenceVerdict]


def build_user_prompt(research: Research, script: Script) -> str:
    facts = "\n".join(f"{i}. {f}" for i, f in enumerate(research.facts, start=1))
    sentences = "\n".join(
        f"{i}. {c.sentence} [cites facts {', '.join(map(str, c.fact_indices))}]"
        for i, c in enumerate(script.citations, start=1)
    )
    return f"Facts:\n{facts}\n\nSentences:\n{sentences}"


def unsupported_sentences(result: CheckResult, script: Script) -> List[str]:
    """返回不被支持的句子（带原因）。缺少某句的判定也视为不通过。"""
    by_number = {v.sentence_number: v for v in result.verdicts}
    problems = []
    for i, c in enumerate(script.citations, start=1):
        v = by_number.get(i)
        if v is None:
            problems.append(f'"{c.sentence}" (no verdict returned)')
        elif not v.supported:
            problems.append(f'"{c.sentence}" ({v.reason})')
    return problems


def make_checker_node(llm: StructuredLLM, log: DecisionLog):
    async def checker(state: TourState) -> Dict[str, Any]:
        lm, research, script = state.selected, state.research, state.script
        base = {"landmark_id": lm.id, "landmark": lm.name, "attempt": state.write_attempts}

        start = time.perf_counter()
        try:
            result = await llm(CheckResult, SYSTEM_PROMPT, build_user_prompt(research, script))
            problems = unsupported_sentences(result, script)
        except LLMError as e:
            problems = [f"checker error: {e}"]
        latency = (time.perf_counter() - start) * 1000

        if not problems:
            log.log("checker", "pass", "passed_check", latency_ms=latency, **base)
            return {"narrated_ids": state.narrated_ids + [lm.id]}

        if state.write_attempts < MAX_WRITE_ATTEMPTS:
            log.log("checker", "retry", "retry", latency_ms=latency, unsupported=problems, **base)
            feedback = "These sentences are not supported by the facts; remove or rewrite them:\n" + "\n".join(problems)
            return {"script": None, "feedback": feedback}

        log.log("checker", "skip", "failed_check", latency_ms=latency, unsupported=problems, **base)
        return {"script": None, "skipped_ids": state.skipped_ids + [lm.id]}

    return checker

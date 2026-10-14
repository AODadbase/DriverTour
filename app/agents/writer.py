"""Writer：只用 Research 中的事实写讲解，每句标注依据的事实编号，并按到达前剩余时间限长。

LLM 只负责写句子和引用编号；word_count / est_seconds / source_url / window_s 全部由代码填写。
"""

import math
import time
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.agents.decision_log import DecisionLog
from app.agents.llm import LLMError, StructuredLLM
from app.agents.scout import SPEECH_WPS, arrival_window_s, distance_to
from app.agents.state import Citation, Research, Script, TourState

MAX_WRITE_ATTEMPTS = 2

SYSTEM_PROMPT = """You are a tour guide speaking to a driver through the car speakers.
Write a short spoken narration about one landmark using ONLY the numbered facts provided.

Strict rules:
- Every statement must come from the facts. Do not add anything else: no dates, numbers, names, history,
  opinions, or descriptive adjectives that the facts do not state. Rephrasing and combining facts is fine.
- Do not mention directions, distances, or what the driver can see; you do not know where it is.
- Each sentence lists the 1-based numbers of the facts it uses in fact_indices.
- Put the most interesting sentence first; later sentences may be cut if time runs out.
- Plain conversational English, no lists, no markdown, at most {max_words} words in total."""


class ScriptDraft(BaseModel):
    citations: List[Citation] = Field(..., description="The narration, one item per sentence, in speaking order.")


class InvalidDraft(Exception):
    pass


def word_count(text: str) -> int:
    return len(text.split())


def build_user_prompt(name: str, research: Research, max_words: int, feedback: Optional[str]) -> str:
    facts = "\n".join(f"{i}. {f}" for i, f in enumerate(research.facts, start=1))
    prompt = f"Landmark: {name}\nWord limit: {max_words}\n\nFacts:\n{facts}"
    if feedback:
        prompt += f"\n\nYour previous attempt was rejected. Fix this:\n{feedback}"
    return prompt


def validate_draft(draft: ScriptDraft, n_facts: int) -> List[Citation]:
    citations = [c for c in draft.citations if c.sentence.strip()]
    if not citations:
        raise InvalidDraft("empty narration")
    for c in citations:
        if not c.fact_indices:
            raise InvalidDraft(f'sentence has no fact_indices: "{c.sentence}"')
        bad = [i for i in c.fact_indices if not 1 <= i <= n_facts]
        if bad:
            raise InvalidDraft(f"fact_indices {bad} out of range 1..{n_facts}")
    return citations


def fit_to_window(citations: List[Citation], max_words: int) -> List[Citation]:
    """从末尾逐句删除直到总词数 <= max_words；每句都有自己的引用，删句不影响溯源。"""
    kept = list(citations)
    while kept and sum(word_count(c.sentence) for c in kept) > max_words:
        kept.pop()
    return kept


def make_writer_node(llm: StructuredLLM, log: DecisionLog):
    async def writer(state: TourState) -> Dict[str, Any]:
        lm, research = state.selected, state.research
        attempts = state.write_attempts + 1
        window_s = arrival_window_s(distance_to(state.position, lm), state.speed_mps)
        max_words = math.floor(window_s * SPEECH_WPS)
        base = {"landmark_id": lm.id, "landmark": lm.name}

        start = time.perf_counter()
        try:
            draft = await llm(ScriptDraft, SYSTEM_PROMPT.format(max_words=max_words),
                              build_user_prompt(lm.name, research, max_words, state.feedback))
            citations = validate_draft(draft, len(research.facts))
        except (LLMError, InvalidDraft) as e:
            latency = (time.perf_counter() - start) * 1000
            retry = attempts < MAX_WRITE_ATTEMPTS
            log.log("writer", "retry" if retry else "skip", "bad_output", latency_ms=latency,
                    attempt=attempts, detail=str(e), **base)
            update: Dict[str, Any] = {"script": None, "write_attempts": attempts}
            if retry:
                update["feedback"] = f"Invalid output: {e}"
            else:
                update["skipped_ids"] = state.skipped_ids + [lm.id]
            return update
        latency = (time.perf_counter() - start) * 1000

        drafted_words = sum(word_count(c.sentence) for c in citations)
        citations = fit_to_window(citations, max_words)
        if not citations:
            log.log("writer", "skip", "too_long", latency_ms=latency, attempt=attempts,
                    drafted_words=drafted_words, max_words=max_words, window_s=round(window_s, 1), **base)
            return {"script": None, "write_attempts": attempts, "feedback": None,
                    "skipped_ids": state.skipped_ids + [lm.id]}

        text = " ".join(c.sentence.strip() for c in citations)
        words = word_count(text)
        script = Script(
            landmark_id=lm.id,
            text=text,
            word_count=words,
            est_seconds=round(words / SPEECH_WPS, 1),
            source_url=research.source_url,
            citations=citations,
            window_s=round(window_s, 1),
        )
        log.log("writer", "write", "written", latency_ms=latency, attempt=attempts,
                word_count=script.word_count, est_seconds=script.est_seconds, window_s=script.window_s,
                fits=script.est_seconds <= script.window_s, drafted_words=drafted_words,
                truncated=drafted_words != words, **base)
        return {"script": script, "write_attempts": attempts, "feedback": None}

    return writer

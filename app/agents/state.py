"""Agent 之间共享的状态。字段与 docs/week-2-design.md 第 4 节逐一对应，改动时两边同步。"""

from typing import List, Optional

from pydantic import BaseModel, Field

from app.models.schemas import POI, GPSPoint

# 地标即 Week 1 的 POI；landmark_id 就是 POI.id（Mapbox id）
Landmark = POI


class Research(BaseModel):
    landmark_id: str
    title: str
    facts: List[str]  # 原文句子，不经过 LLM
    source_url: str


class Citation(BaseModel):
    sentence: str = Field(..., description="One sentence of the narration.")
    fact_indices: List[int] = Field(..., description="1-based numbers of the facts this sentence is based on.")


class Script(BaseModel):
    landmark_id: str
    text: str
    word_count: int
    est_seconds: float
    source_url: str  # 从 Research 复制，不由 LLM 生成
    citations: List[Citation]
    window_s: float  # 生成时距离到达的秒数


class TourState(BaseModel):
    position: GPSPoint
    heading: Optional[float]
    speed_mps: float
    candidates: List[Landmark]
    selected: Optional[Landmark] = None
    research: Optional[Research] = None
    script: Optional[Script] = None
    narrated_ids: List[str] = []
    skipped_ids: List[str] = []
    feedback: Optional[str] = None
    write_attempts: int = 0

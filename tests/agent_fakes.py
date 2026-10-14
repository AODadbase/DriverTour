"""Agent 测试共用的假数据与假 LLM（不联网、不需要 API key）。"""

from typing import List

from app.agents.state import Landmark, Research, TourState
from app.models.schemas import GPSPoint

# 车在 (40.0, -88.0)，向北行驶，10 m/s
CAR = GPSPoint(lat=40.0, lng=-88.0)


def landmark(id_: str, dlat: float = 0.002, dlng: float = 0.0, name: str = "Test Museum") -> Landmark:
    """默认在车正北约 222 m。"""
    return Landmark(id=id_, name=name, lat=CAR.lat + dlat, lng=CAR.lng + dlng)


def state(candidates: List[Landmark], **kw) -> TourState:
    base = dict(position=CAR, heading=0.0, speed_mps=10.0, candidates=candidates)
    base.update(kw)
    return TourState(**base)


RESEARCH = Research(
    landmark_id="a",
    title="Test Museum",
    facts=["The Test Museum is an art museum.", "It opened to the public in 1950.", "It holds over 9,000 works."],
    source_url="https://en.wikipedia.org/wiki/Test_Museum",
)


class FakeLLM:
    """按 schema 类名依次弹出预设回复；回复可以是实例或异常。记录每次调用的 prompt。"""

    def __init__(self, **responses):
        self.responses = {k: list(v) for k, v in responses.items()}
        self.calls = []

    async def __call__(self, schema, system, user):
        self.calls.append((schema.__name__, system, user))
        resp = self.responses[schema.__name__].pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp

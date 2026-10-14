"""Scout：从候选地标中选出一个"在前方、没讲过、来得及讲"的，或者一个都不选。

纯计算，不联网、不调用 LLM，因此 run_tour 可以每个 ping 都调用 select_landmark 做预检。
"""

from typing import Any, Dict, Optional

from app.agents.decision_log import DecisionLog
from app.agents.state import Landmark, TourState
from app.geo.bearing import MIN_HEADING_SPEED_MPS, bearing, is_ahead
from app.models.schemas import GPSPoint
from app.services.geo import haversine_m

MAX_RANGE_M = 600.0  # 超过该距离暂不考虑
PASSING_M = 20.0  # 小于该距离视为正在经过，方位角已无意义
CONE_DEG = 60.0  # 前方扇形的单侧半角
MIN_WINDOW_S = 8.0  # 来不及讲完一句话
MAX_WINDOW_S = 45.0  # 单段讲解时长上限
SPEECH_WPS = 2.5  # 英文语速：词 / 秒


def arrival_window_s(distance_m: float, speed_mps: float) -> float:
    """按当前车速到达地标所需秒数，上限 MAX_WINDOW_S；低速时直接取上限。"""
    if speed_mps < MIN_HEADING_SPEED_MPS:
        return MAX_WINDOW_S
    return min(distance_m / speed_mps, MAX_WINDOW_S)


def distance_to(position: GPSPoint, lm: Landmark) -> float:
    return haversine_m(position.lat, position.lng, lm.lat, lm.lng)


def _reject_reason(state: TourState, lm: Landmark, dist: float) -> Optional[str]:
    if lm.id in state.narrated_ids:
        return "already_narrated"
    if lm.id in state.skipped_ids:
        return "already_skipped"
    if dist > MAX_RANGE_M:
        return "out_of_range"
    if state.heading is None or dist < PASSING_M:
        return "behind"
    if not is_ahead(state.heading, bearing(state.position, GPSPoint(lat=lm.lat, lng=lm.lng)), CONE_DEG):
        return "behind"
    if arrival_window_s(dist, state.speed_mps) < MIN_WINDOW_S:
        return "too_close"
    return None


def select_landmark(state: TourState, log: Optional[DecisionLog] = None) -> Optional[Landmark]:
    """按设计文档 6.2 的规则过滤，返回距离最近的合格地标；拒绝原因按变化写日志。"""
    best: Optional[Landmark] = None
    best_dist = float("inf")

    for lm in state.candidates:
        dist = distance_to(state.position, lm)
        reason = _reject_reason(state, lm, dist)
        if reason is None:
            if dist < best_dist:
                best, best_dist = lm, dist
            continue
        if log:
            log.log_on_change(
                "scout", "reject", reason, lm.id, landmark=lm.name, **_geo_detail(state, lm, dist)
            )
    return best


def _geo_detail(state: TourState, lm: Landmark, dist: float) -> Dict[str, Any]:
    b = bearing(state.position, GPSPoint(lat=lm.lat, lng=lm.lng))
    return {
        "distance_m": round(dist, 1),
        "bearing": round(b, 1),
        "heading": None if state.heading is None else round(state.heading, 1),
    }


def make_scout_node(log: DecisionLog):
    async def scout(state: TourState) -> Dict[str, Any]:
        selected = select_landmark(state, log)
        if selected is None:
            log.log("scout", "none", "nothing_selected", candidates=len(state.candidates))
            return {"selected": None}

        dist = distance_to(state.position, selected)
        log.log(
            "scout",
            "select",
            "selected",
            landmark_id=selected.id,
            landmark=selected.name,
            window_s=round(arrival_window_s(dist, state.speed_mps), 1),
            speed_mps=round(state.speed_mps, 1),
            **_geo_detail(state, selected, dist),
        )
        return {"selected": selected}

    return scout

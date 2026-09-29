"""按时间顺序重放轨迹，模拟用户移动。"""

import asyncio
from typing import AsyncIterator, Awaitable, Callable, Iterator, List, Optional

from app.models.schemas import ReplayPoint, Track
from app.services.geo import cumulative_distances


def iter_replay(track: Track, speed: float = 1.0) -> Iterator[ReplayPoint]:
    """逐点 yield，并计算按 speed 缩放后的"应到达时间"，不 sleep。

    相邻点缺少时间戳时，视为 Δt = 0。
    """
    if speed <= 0:
        raise ValueError("speed must be > 0")

    dists = cumulative_distances(track.points)
    offset = 0.0
    for i, point in enumerate(track.points):
        if i > 0:
            prev = track.points[i - 1]
            if prev.timestamp is not None and point.timestamp is not None:
                dt = (point.timestamp - prev.timestamp).total_seconds()
                offset += max(dt, 0.0) / speed
        yield ReplayPoint(index=i, point=point, cumulative_distance_m=dists[i], offset_s=offset)


async def replay(
    track: Track,
    speed: float = 1.0,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> AsyncIterator[ReplayPoint]:
    """实时重放：相邻点之间 sleep Δt / speed。sleep 可注入，便于测试。"""
    last_offset = 0.0
    for rp in iter_replay(track, speed):
        wait = rp.offset_s - last_offset
        if wait > 0:
            await sleep(wait)
        last_offset = rp.offset_s
        yield rp


def select_query_points(
    replay_points: List[ReplayPoint],
    step: Optional[int] = None,
    min_distance_m: Optional[float] = None,
) -> List[ReplayPoint]:
    """决定在哪些点触发 POI 查询。

    - min_distance_m：距上一次查询点移动超过阈值才再次查询（优先）
    - step：每隔 N 个点查一次
    起点总是会被查询。
    """
    if not replay_points:
        return []

    if min_distance_m is not None:
        selected = [replay_points[0]]
        for rp in replay_points[1:]:
            if rp.cumulative_distance_m - selected[-1].cumulative_distance_m >= min_distance_m:
                selected.append(rp)
        return selected

    step = step or 1
    return replay_points[::step]

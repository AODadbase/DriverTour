"""方位角、角度差与"是否在前方"判断，以及由连续 GPS 点估计航向/速度。

约定：角度单位为度，0 = 正北，顺时针增加（90 = 正东）。
"""

import math
from typing import Optional

from app.models.schemas import GPSPoint
from app.services.geo import distance_between

# 低于该速度时 GPS 抖动会让方位角失去意义，保留上一个有效航向
MIN_HEADING_SPEED_MPS = 2.0


def bearing(from_: GPSPoint, to: GPSPoint) -> float:
    """from_ 指向 to 的初始方位角，范围 [0, 360)。

    θ = atan2(sin Δλ · cos φ2, cos φ1 · sin φ2 − sin φ1 · cos φ2 · cos Δλ)
    """
    phi1, phi2 = math.radians(from_.lat), math.radians(to.lat)
    d_lambda = math.radians(to.lng - from_.lng)

    x = math.sin(d_lambda) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(d_lambda)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def angle_diff(a: float, b: float) -> float:
    """从 a 转到 b 的有符号最小角度，范围 [-180, 180)。正数表示 b 在 a 的顺时针方向（右侧）。

    例：angle_diff(350, 10) == 20，而不是 -340。
    """
    return (b - a + 180.0) % 360.0 - 180.0


def is_ahead(heading: float, bearing_to_target: float, cone_deg: float = 60.0) -> bool:
    """目标是否位于以 heading 为中心、左右各 cone_deg 度的扇形内。"""
    return abs(angle_diff(heading, bearing_to_target)) <= cone_deg


class HeadingTracker:
    """逐点喂入 GPS 点，维护当前航向与速度。

    - 速度 = 相邻两点距离 / Δt；缺少时间戳或 Δt <= 0 时速度记为 0
    - 速度 < min_speed_mps 时不更新航向（停车或缓行时 GPS 抖动会给出随机方位）
    - 缺少时间戳时无法判断速度，只要位置有移动就更新航向
    """

    def __init__(self, min_speed_mps: float = MIN_HEADING_SPEED_MPS):
        self.min_speed_mps = min_speed_mps
        self.heading: Optional[float] = None
        self.speed_mps: float = 0.0
        self._prev: Optional[GPSPoint] = None

    def update(self, point: GPSPoint) -> None:
        prev, self._prev = self._prev, point
        if prev is None:
            return

        dist = distance_between(prev, point)
        if prev.timestamp is not None and point.timestamp is not None:
            dt = (point.timestamp - prev.timestamp).total_seconds()
            self.speed_mps = dist / dt if dt > 0 else 0.0
            moving = self.speed_mps >= self.min_speed_mps
        else:
            self.speed_mps = 0.0
            moving = dist > 1.0

        if moving:
            self.heading = bearing(prev, point)

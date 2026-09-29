"""地理计算：Haversine 球面距离、累计距离、半径 → bbox。"""

import math
from typing import List, Sequence, Tuple

from app.models.schemas import GPSPoint

EARTH_RADIUS_M = 6_371_000.0


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """两点间球面距离（米）。

    a = sin²(Δφ/2) + cos φ1 · cos φ2 · sin²(Δλ/2)
    d = 2R · atan2(√a, √(1−a))
    """
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)

    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def distance_between(a: GPSPoint, b: GPSPoint) -> float:
    return haversine_m(a.lat, a.lng, b.lat, b.lng)


def cumulative_distances(points: Sequence[GPSPoint]) -> List[float]:
    """返回每个点距起点的累计距离，首元素为 0。"""
    result: List[float] = []
    total = 0.0
    for i, p in enumerate(points):
        if i > 0:
            total += distance_between(points[i - 1], p)
        result.append(total)
    return result


def total_distance(points: Sequence[GPSPoint]) -> float:
    dists = cumulative_distances(points)
    return dists[-1] if dists else 0.0


def bounding_box(lat: float, lng: float, radius_m: float) -> Tuple[float, float, float, float]:
    """以 (lat, lng) 为中心、radius_m 为半径的近似外接矩形。

    返回 Mapbox 的 bbox 顺序：(min_lng, min_lat, max_lng, max_lat)。
    """
    d_lat = math.degrees(radius_m / EARTH_RADIUS_M)
    cos_lat = max(math.cos(math.radians(lat)), 1e-6)  # 极点附近避免除零
    d_lng = min(math.degrees(radius_m / (EARTH_RADIUS_M * cos_lat)), 180.0)

    return (
        max(lng - d_lng, -180.0),
        max(lat - d_lat, -90.0),
        min(lng + d_lng, 180.0),
        min(lat + d_lat, 90.0),
    )

"""封装 Mapbox Search Box API（category search）。

文档：https://docs.mapbox.com/api/search/search-box/#category-search
GET /search/searchbox/v1/category/{canonical_category_id}

注意：Mapbox 坐标顺序是 lng,lat；内部模型统一 lat/lng，转换只在本模块发生。
"""

from typing import Any, Dict, List, Optional

import httpx

from app.models.schemas import POI, GPSPoint
from app.services.geo import bounding_box, haversine_m


class POIClientError(Exception):
    pass


class MapboxPOIClient:
    def __init__(
        self,
        access_token: str,
        http_client: httpx.AsyncClient,
        base_url: str = "https://api.mapbox.com/search/searchbox/v1",
        default_category: str = "restaurant",
        limit: int = 10,
    ):
        self._token = access_token
        self._http = http_client
        self._base_url = base_url.rstrip("/")
        self._default_category = default_category
        self._limit = limit

    async def search_nearby(
        self,
        center: GPSPoint,
        radius_m: int,
        category: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[POI]:
        """检索 center 周边 radius_m 米内的 POI，按距离升序返回。

        Category search 没有 radius 参数，因此用 bbox 粗筛，再用 Haversine 精确过滤。
        """
        if not self._token:
            raise POIClientError("MAPBOX_ACCESS_TOKEN is not configured")

        category = category or self._default_category
        min_lng, min_lat, max_lng, max_lat = bounding_box(center.lat, center.lng, radius_m)
        params = {
            "access_token": self._token,
            "proximity": f"{center.lng},{center.lat}",
            "bbox": f"{min_lng},{min_lat},{max_lng},{max_lat}",
            "limit": min(limit or self._limit, 25),
        }

        try:
            resp = await self._http.get(f"{self._base_url}/category/{category}", params=params)
        except httpx.HTTPError as e:
            raise POIClientError(f"Mapbox request failed: {e.__class__.__name__}") from e

        if resp.status_code != 200:
            # 不把带 token 的 URL 带进错误信息
            raise POIClientError(f"Mapbox returned HTTP {resp.status_code}: {_error_message(resp)}")

        features = resp.json().get("features", [])
        pois = [poi for f in features if (poi := feature_to_poi(f, center, category)) is not None]
        pois = [p for p in pois if p.distance_m is not None and p.distance_m <= radius_m]
        pois.sort(key=lambda p: p.distance_m)
        return pois


def feature_to_poi(feature: Dict[str, Any], center: GPSPoint, category: Optional[str] = None) -> Optional[POI]:
    """把 Mapbox GeoJSON Feature 映射成内部 POI 模型，字段缺失时返回 None。"""
    props = feature.get("properties") or {}

    coords = props.get("coordinates") or {}
    lat, lng = coords.get("latitude"), coords.get("longitude")
    if lat is None or lng is None:
        geom = (feature.get("geometry") or {}).get("coordinates") or []
        if len(geom) < 2:
            return None
        lng, lat = geom[0], geom[1]  # GeoJSON: [lng, lat]

    poi_id = props.get("mapbox_id") or feature.get("id")
    name = props.get("name")
    if not poi_id or not name:
        return None

    category_ids = props.get("poi_category_ids") or []
    return POI(
        id=poi_id,
        name=name,
        category=category or (category_ids[0] if category_ids else None),
        lat=lat,
        lng=lng,
        address=props.get("full_address") or props.get("address"),
        distance_m=round(haversine_m(center.lat, center.lng, lat, lng), 1),
    )


def _error_message(resp: httpx.Response) -> str:
    try:
        return resp.json().get("message", "")
    except ValueError:
        return ""

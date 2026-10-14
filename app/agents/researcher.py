"""Researcher：按坐标在 Wikipedia 上找到地标对应的条目，把摘要切成短事实并附上 URL。

宁缺毋滥：名称或距离对不上、页面不是普通条目、事实太少，一律返回 None（no_source），绝不猜。

API：
- geosearch：https://en.wikipedia.org/w/api.php?action=query&list=geosearch&gscoord=LAT|LON&gsradius=500
- summary：  https://en.wikipedia.org/api/rest_v1/page/summary/{title}
"""

import re
import time
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import httpx

from app.agents.decision_log import DecisionLog
from app.agents.state import Landmark, Research, TourState
from app.services.geo import haversine_m

GEOSEARCH_RADIUS_M = 500
MAX_MATCH_DISTANCE_M = 300.0
MIN_NAME_SIMILARITY = 0.6
MIN_FACTS = 2
MAX_FACTS = 5


class WikipediaError(Exception):
    pass


class NoSource(Exception):
    """没有可信来源；args[0] 是具体原因，写进日志。"""


class WikipediaClient:
    def __init__(
        self,
        http_client: httpx.AsyncClient,
        user_agent: str,
        api_url: str = "https://en.wikipedia.org/w/api.php",
        rest_url: str = "https://en.wikipedia.org/api/rest_v1",
    ):
        self._http = http_client
        self._headers = {"User-Agent": user_agent}
        self._api_url = api_url
        self._rest_url = rest_url.rstrip("/")

    async def geosearch(self, lat: float, lng: float, radius_m: int = GEOSEARCH_RADIUS_M) -> List[Dict[str, Any]]:
        params = {
            "action": "query",
            "list": "geosearch",
            "gscoord": f"{lat}|{lng}",
            "gsradius": radius_m,
            "gslimit": 10,
            "format": "json",
        }
        data = await self._get_json(self._api_url, params)
        return (data.get("query") or {}).get("geosearch") or []

    async def summary(self, title: str) -> Dict[str, Any]:
        return await self._get_json(f"{self._rest_url}/page/summary/{quote(title.replace(' ', '_'), safe='')}")

    async def _get_json(self, url: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        try:
            resp = await self._http.get(url, params=params, headers=self._headers, follow_redirects=True)
        except httpx.HTTPError as e:
            raise WikipediaError(f"request failed: {e.__class__.__name__}") from e
        if resp.status_code != 200:
            raise WikipediaError(f"HTTP {resp.status_code}")
        try:
            return resp.json()
        except ValueError as e:
            raise WikipediaError("invalid JSON") from e


def normalize_name(name: str) -> str:
    """转小写、去掉括号内容（如 "(Illinois)"）和标点，合并空白。"""
    name = re.sub(r"\([^)]*\)", " ", name.lower())
    name = re.sub(r"[^\w\s]", " ", name)
    return " ".join(name.split())


def name_similarity(a: str, b: str) -> float:
    """SequenceMatcher 比值与"较短名称的词全部出现在较长名称中"两者取大。"""
    na, nb = normalize_name(a), normalize_name(b)
    if not na or not nb:
        return 0.0
    ratio = SequenceMatcher(None, na, nb).ratio()
    ta, tb = set(na.split()), set(nb.split())
    short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    # 只有一个词时太容易误中（如 "Park"），不算包含
    contained = 0.9 if len(short) >= 2 and short <= long_ else 0.0
    return max(ratio, contained)


def best_match(lm: Landmark, hits: List[Dict[str, Any]]) -> Optional[Tuple[Dict[str, Any], float, float]]:
    """返回 (条目, 名称相似度, 距离米)；没有同时满足名称和距离阈值的条目时返回 None。"""
    best = None
    for hit in hits:
        sim = name_similarity(lm.name, hit.get("title", ""))
        dist = haversine_m(lm.lat, lm.lng, hit["lat"], hit["lon"])
        if sim < MIN_NAME_SIMILARITY or dist > MAX_MATCH_DISTANCE_M:
            continue
        if best is None or sim > best[1]:
            best = (hit, sim, dist)
    return best


_ABBREVIATIONS = ("St.", "Mt.", "Dr.", "Mr.", "Mrs.", "Ms.", "Jr.", "Sr.", "U.S.", "U.K.", "Inc.", "Co.", "No.", "Ave.")


def split_facts(extract: str) -> List[str]:
    """把摘要按句切开。句末标点后接空白和大写字母/数字/引号才算断句，并跳过常见缩写。"""
    sentences: List[str] = []
    buf = ""
    for part in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"“])", extract.strip()):
        buf = f"{buf} {part}".strip() if buf else part.strip()
        if buf.endswith(_ABBREVIATIONS):
            continue
        sentences.append(buf)
        buf = ""
    if buf:
        sentences.append(buf)
    return [s for s in sentences if len(s.split()) >= 3]


async def research_landmark(client: WikipediaClient, lm: Landmark) -> Tuple[Research, Dict[str, Any]]:
    """成功时返回 (Research, 日志细节)；失败时抛 NoSource(原因)。"""
    try:
        hits = await client.geosearch(lm.lat, lm.lng)
    except WikipediaError as e:
        raise NoSource(f"http_error: {e}")
    if not hits:
        raise NoSource("no_geosearch_hit")

    match = best_match(lm, hits)
    if match is None:
        nearest = ", ".join(h.get("title", "") for h in hits[:3])
        raise NoSource(f"no_name_match (nearby: {nearest})")
    hit, sim, dist = match

    try:
        page = await client.summary(hit["title"])
    except WikipediaError as e:
        raise NoSource(f"http_error: {e}")
    if page.get("type") != "standard":
        raise NoSource(f"not_standard_page ({page.get('type')})")

    facts = split_facts(page.get("extract") or "")[:MAX_FACTS]
    url = ((page.get("content_urls") or {}).get("desktop") or {}).get("page")
    if len(facts) < MIN_FACTS:
        raise NoSource(f"too_few_facts ({len(facts)})")
    if not url:
        raise NoSource("no_url")

    research = Research(landmark_id=lm.id, title=page.get("title") or hit["title"], facts=facts, source_url=url)
    return research, {"wiki_title": research.title, "name_similarity": round(sim, 2), "match_distance_m": round(dist, 1)}


def make_researcher_node(client: WikipediaClient, log: DecisionLog):
    async def researcher(state: TourState) -> Dict[str, Any]:
        lm = state.selected
        start = time.perf_counter()
        try:
            research, detail = await research_landmark(client, lm)
        except NoSource as e:
            log.log(
                "researcher", "skip", "no_source", landmark_id=lm.id, landmark=lm.name,
                latency_ms=(time.perf_counter() - start) * 1000, detail=str(e),
            )
            return {"research": None, "skipped_ids": state.skipped_ids + [lm.id]}

        log.log(
            "researcher", "research", "researched", landmark_id=lm.id, landmark=lm.name,
            latency_ms=(time.perf_counter() - start) * 1000,
            source_url=research.source_url, facts=research.facts, **detail,
        )
        return {"research": research}

    return researcher

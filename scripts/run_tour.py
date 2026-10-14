"""端到端运行：重放 GPX → 刷新周边地标 → Agent 图 → 打印讲解词，决策写入 logs/run.jsonl。

每个 ping 都用 select_landmark 做一次纯计算预检，只有选出新地标、且上一段讲解已播完（按行驶时间）
才调用 Agent 图，避免每个 ping 都调用 LLM。

用法：
    python -m scripts.run_tour
    python -m scripts.run_tour --gpx data/sample.gpx --speed 20   # 按 20 倍速实时重放
"""

import argparse
import asyncio
import json
from pathlib import Path
from typing import Dict, List

import httpx

from app.agents.decision_log import DecisionLog
from app.agents.graph import build_graph, run_graph
from app.agents.llm import make_deepseek_llm
from app.agents.researcher import WikipediaClient
from app.agents.scout import select_landmark
from app.agents.state import Landmark, TourState
from app.config import get_settings
from app.geo.bearing import HeadingTracker
from app.models.schemas import GPSPoint
from app.services.gpx_parser import parse_gpx_file
from app.services.poi_client import MapboxPOIClient, POIClientError
from app.services.replayer import replay


async def refresh_landmarks(
    client: MapboxPOIClient, center: GPSPoint, radius: int, categories: List[str], pool: Dict[str, Landmark]
) -> None:
    """按多个地标类分类查询周边 POI 并并入候选池；无效分类报一次错后移除。"""
    results = await asyncio.gather(
        *(client.search_nearby(center, radius_m=radius, category=c) for c in categories), return_exceptions=True
    )
    for category, res in zip(list(categories), results):
        if isinstance(res, POIClientError):
            print(f"    !! 分类 {category} 查询失败，后续不再查询：{res}")
            categories.remove(category)
            continue
        for lm in res:
            pool.setdefault(lm.id, lm)


async def main(args: argparse.Namespace) -> None:
    settings = get_settings()
    if not settings.mapbox_access_token:
        raise SystemExit("MAPBOX_ACCESS_TOKEN 未配置")
    llm = make_deepseek_llm(settings)
    categories = [c.strip() for c in (args.categories or settings.landmark_categories).split(",") if c.strip()]

    track = parse_gpx_file(args.gpx, track_id="tour")
    log = DecisionLog(args.log)
    print(f"Track '{track.name}': {len(track.points)} points, {track.total_distance_m:.0f} m")
    print(f"Categories: {', '.join(categories)}\n")

    tracker = HeadingTracker()
    pool: Dict[str, Landmark] = {}
    narrated_ids: List[str] = []
    skipped_ids: List[str] = []
    scripts = []
    last_refresh_m = None
    busy_until = 0.0  # 上一段讲解播完的行驶时间（秒）

    async with httpx.AsyncClient(timeout=settings.http_timeout_s) as http:
        poi_client = MapboxPOIClient(
            access_token=settings.mapbox_access_token,
            http_client=http,
            base_url=settings.mapbox_base_url,
            limit=settings.poi_limit,
        )
        graph = build_graph(llm, WikipediaClient(http, settings.wikipedia_user_agent), log)

        async for rp in replay(track, speed=args.speed):
            t_drive = rp.offset_s * args.speed  # 还原为真实行驶时间
            log.t_sim = round(t_drive, 1)
            tracker.update(rp.point)

            if last_refresh_m is None or rp.cumulative_distance_m - last_refresh_m >= args.refresh_m:
                last_refresh_m = rp.cumulative_distance_m
                before = len(pool)
                await refresh_landmarks(poi_client, rp.point, args.radius, categories, pool)
                print(f"[{t_drive:6.1f}s] #{rp.index:<3} 刷新地标：新增 {len(pool) - before}，候选池 {len(pool)}")

            state = TourState(
                position=rp.point,
                heading=tracker.heading,
                speed_mps=tracker.speed_mps,
                candidates=list(pool.values()),
                narrated_ids=narrated_ids,
                skipped_ids=skipped_ids,
            )
            if t_drive < busy_until or select_landmark(state, log) is None:
                continue

            final = await run_graph(graph, state)
            narrated_ids, skipped_ids = final.narrated_ids, final.skipped_ids
            if final.script is None:
                print(f"[{t_drive:6.1f}s] #{rp.index:<3} 跳过 {final.selected.name}（原因见日志）")
                continue

            s = final.script
            busy_until = t_drive + s.est_seconds
            scripts.append({
                "t_drive": round(t_drive, 1),
                "landmark": final.selected.name,
                "script": s.model_dump(),
                "facts": final.research.facts,
            })
            print(f"\n[{t_drive:6.1f}s] #{rp.index:<3} ▶ {final.selected.name}  "
                  f"({s.word_count} words, {s.est_seconds}s / window {s.window_s}s)")
            print(f"    {s.text}")
            print(f"    source: {s.source_url}\n")

    out = Path(args.log).with_name("scripts.json")
    out.write_text(json.dumps(scripts, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n完成：{len(scripts)} 段讲解，跳过 {len(skipped_ids)} 个地标。日志 {args.log}，讲解词 {out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--gpx", default="data/sample.gpx")
    parser.add_argument("--speed", type=float, default=1000.0, help="重放倍速；默认基本不等待")
    parser.add_argument("--refresh-m", type=float, default=400.0, help="每行驶多少米刷新一次地标")
    parser.add_argument("--radius", type=int, default=600, help="地标查询半径（米）")
    parser.add_argument("--categories", default=None, help="逗号分隔的 Mapbox 分类，默认 LANDMARK_CATEGORIES")
    parser.add_argument("--log", default="logs/run.jsonl")
    asyncio.run(main(parser.parse_args()))

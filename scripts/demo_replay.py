"""命令行 Demo：实时重放轨迹，每移动一定距离查询一次周边 POI。

用法：
    python -m scripts.demo_replay --speed 20 --min-distance 400 --category cafe
"""

import argparse
import asyncio

import httpx

from app.config import get_settings
from app.services.gpx_parser import parse_gpx_file
from app.services.poi_client import MapboxPOIClient, POIClientError
from app.services.replayer import replay


async def main(args: argparse.Namespace) -> None:
    settings = get_settings()
    track = parse_gpx_file(args.gpx, track_id="demo")
    print(f"Track '{track.name}': {len(track.points)} points, {track.total_distance_m:.0f} m, speed x{args.speed}")
    if not settings.mapbox_access_token:
        print("!! MAPBOX_ACCESS_TOKEN 未配置，只重放位置，不查询 POI\n")

    async with httpx.AsyncClient(timeout=settings.http_timeout_s) as http:
        client = MapboxPOIClient(
            access_token=settings.mapbox_access_token,
            http_client=http,
            base_url=settings.mapbox_base_url,
            default_category=settings.default_poi_category,
            limit=settings.poi_limit,
        )
        last_query_at = None
        async for rp in replay(track, speed=args.speed):
            p = rp.point
            print(f"[{rp.offset_s:6.1f}s] #{rp.index:<3} ({p.lat:.5f}, {p.lng:.5f})  {rp.cumulative_distance_m:7.0f} m")

            due = last_query_at is None or rp.cumulative_distance_m - last_query_at >= args.min_distance
            if not (due and settings.mapbox_access_token):
                continue
            last_query_at = rp.cumulative_distance_m
            try:
                pois = await client.search_nearby(p, radius_m=args.radius, category=args.category)
            except POIClientError as e:
                print(f"    POI 查询失败：{e}")
                continue
            if not pois:
                print(f"    {args.radius} m 内没有 POI")
            for poi in pois[:5]:
                print(f"    - {poi.name} ({poi.category}) {poi.distance_m:.0f} m  {poi.address or ''}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--gpx", default="data/sample.gpx")
    parser.add_argument("--speed", type=float, default=20.0, help="重放倍速")
    parser.add_argument("--min-distance", type=float, default=400.0, help="移动超过该距离（米）才再次查询")
    parser.add_argument("--radius", type=int, default=500)
    parser.add_argument("--category", default=None, help="默认使用 DEFAULT_POI_CATEGORY")
    asyncio.run(main(parser.parse_args()))

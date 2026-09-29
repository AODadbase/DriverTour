import asyncio
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status

from app.config import Settings, get_settings
from app.models.schemas import (
    GPSPoint,
    POISearchResponse,
    ReplayPoint,
    ReplayResponse,
    Track,
    TrackPOIResponse,
    TrackPOIStop,
)
from app.services.gpx_parser import GPXParseError, parse_gpx
from app.services.poi_client import MapboxPOIClient, POIClientError
from app.services.replayer import iter_replay, select_query_points
from app.services.track_store import TrackStore

router = APIRouter()

MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def get_track_store(request: Request) -> TrackStore:
    return request.app.state.track_store


def get_poi_client(request: Request) -> MapboxPOIClient:
    return request.app.state.poi_client


def _get_track_or_404(store: TrackStore, track_id: str) -> Track:
    track = store.get(track_id)
    if track is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Track '{track_id}' not found")
    return track


async def _search(
    client: MapboxPOIClient, center: GPSPoint, radius: int, category: Optional[str]
) -> POISearchResponse:
    try:
        results = await client.search_nearby(center, radius_m=radius, category=category)
    except POIClientError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from e
    return POISearchResponse(center=center, radius_m=radius, results=results)


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@router.post("/tracks", response_model=Track, status_code=status.HTTP_201_CREATED)
async def upload_track(
    file: UploadFile = File(..., description="GPX 文件"),
    store: TrackStore = Depends(get_track_store),
) -> Track:
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "GPX file too large")
    try:
        track = parse_gpx(content, track_id=store.new_id())
    except GPXParseError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    if track.name is None and file.filename:
        track.name = file.filename
    return store.add(track)


@router.get("/tracks/{track_id}/replay", response_model=ReplayResponse)
async def replay_track(
    track_id: str,
    speed: float = Query(10.0, gt=0, description="重放倍速"),
    store: TrackStore = Depends(get_track_store),
) -> ReplayResponse:
    track = _get_track_or_404(store, track_id)
    points = list(iter_replay(track, speed))
    return ReplayResponse(
        track_id=track.id,
        speed=speed,
        duration_s=points[-1].offset_s if points else 0.0,
        points=points,
    )


@router.get("/pois", response_model=POISearchResponse)
async def search_pois(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    radius: int = Query(500, gt=0, le=10_000, description="半径（米）"),
    category: Optional[str] = Query(None, description="Mapbox canonical category id，如 cafe / restaurant"),
    client: MapboxPOIClient = Depends(get_poi_client),
) -> POISearchResponse:
    return await _search(client, GPSPoint(lat=lat, lng=lng), radius, category)


@router.get("/tracks/{track_id}/pois", response_model=TrackPOIResponse)
async def track_pois(
    track_id: str,
    step: int = Query(5, ge=1, description="每隔 N 个点查询一次"),
    min_distance_m: Optional[float] = Query(
        None, gt=0, description="距上次查询移动超过该距离才查询；设置后忽略 step"
    ),
    radius: int = Query(500, gt=0, le=10_000),
    category: Optional[str] = Query(None),
    speed: float = Query(10.0, gt=0),
    store: TrackStore = Depends(get_track_store),
    client: MapboxPOIClient = Depends(get_poi_client),
    settings: Settings = Depends(get_settings),
) -> TrackPOIResponse:
    """Demo：重放轨迹，在选中的点上查询周边 POI。"""
    track = _get_track_or_404(store, track_id)
    selected = select_query_points(list(iter_replay(track, speed)), step=step, min_distance_m=min_distance_m)

    limit = settings.max_poi_queries_per_track
    truncated = len(selected) > limit
    selected = selected[:limit]

    sem = asyncio.Semaphore(settings.poi_query_concurrency)

    async def query(rp: ReplayPoint) -> TrackPOIStop:
        async with sem:
            pois = await _search(client, rp.point, radius, category)
        return TrackPOIStop(replay=rp, pois=pois)

    stops: List[TrackPOIStop] = await asyncio.gather(*(query(rp) for rp in selected))
    return TrackPOIResponse(track_id=track.id, stops=stops, truncated=truncated)

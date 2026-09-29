import logging
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI

from app.api.routes import router
from app.config import get_settings
from app.services.gpx_parser import parse_gpx_file
from app.services.poi_client import MapboxPOIClient
from app.services.track_store import TrackStore

logger = logging.getLogger(__name__)

SAMPLE_TRACK_ID = "sample"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    app.state.track_store = TrackStore()
    sample = Path(settings.sample_gpx_path)
    if sample.exists():
        app.state.track_store.add(parse_gpx_file(sample, track_id=SAMPLE_TRACK_ID))
        logger.info("Loaded sample track '%s' from %s", SAMPLE_TRACK_ID, sample)

    if not settings.mapbox_access_token:
        logger.warning("MAPBOX_ACCESS_TOKEN is not set; POI endpoints will return 502")

    async with httpx.AsyncClient(timeout=settings.http_timeout_s) as http_client:
        app.state.poi_client = MapboxPOIClient(
            access_token=settings.mapbox_access_token,
            http_client=http_client,
            base_url=settings.mapbox_base_url,
            default_category=settings.default_poi_category,
            limit=settings.poi_limit,
        )
        yield


app = FastAPI(title="DriverTour", version="0.1.0", lifespan=lifespan)
app.include_router(router)

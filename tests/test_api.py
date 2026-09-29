from pathlib import Path
from typing import List, Optional

import pytest
from fastapi.testclient import TestClient

from app.api.routes import get_poi_client
from app.main import app
from app.models.schemas import POI, GPSPoint
from app.services.poi_client import POIClientError

SAMPLE = Path(__file__).resolve().parent.parent / "data" / "sample.gpx"


class FakePOIClient:
    def __init__(self, fail: bool = False):
        self.calls: List[GPSPoint] = []
        self.fail = fail

    async def search_nearby(self, center: GPSPoint, radius_m: int, category: Optional[str] = None, limit=None):
        self.calls.append(center)
        if self.fail:
            raise POIClientError("Mapbox returned HTTP 401: Not Authorized")
        return [POI(id="poi.1", name="Example Cafe", category=category or "cafe", lat=center.lat, lng=center.lng,
                    distance_m=0.0)]


@pytest.fixture
def fake_poi():
    return FakePOIClient()


@pytest.fixture
def client(fake_poi):
    app.dependency_overrides[get_poi_client] = lambda: fake_poi
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_upload_and_replay(client):
    resp = client.post("/tracks", files={"file": ("sample.gpx", SAMPLE.read_bytes(), "application/gpx+xml")})
    assert resp.status_code == 201
    track = resp.json()
    assert len(track["points"]) == 38

    replay = client.get(f"/tracks/{track['id']}/replay", params={"speed": 10}).json()
    assert len(replay["points"]) == 38
    assert replay["duration_s"] == pytest.approx(37.0)  # 37 段 × 10 s / 10


def test_upload_invalid_gpx(client):
    resp = client.post("/tracks", files={"file": ("bad.gpx", b"not gpx", "application/gpx+xml")})
    assert resp.status_code == 400


def test_sample_track_preloaded(client):
    assert client.get("/tracks/sample/replay").status_code == 200


def test_unknown_track_404(client):
    assert client.get("/tracks/nope/replay").status_code == 404


def test_replay_rejects_bad_speed(client):
    assert client.get("/tracks/sample/replay", params={"speed": 0}).status_code == 422


def test_search_pois(client, fake_poi):
    resp = client.get("/pois", params={"lat": 40.1106, "lng": -88.2073, "radius": 500, "category": "cafe"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["center"]["lat"] == 40.1106
    assert body["radius_m"] == 500
    assert body["results"][0]["category"] == "cafe"


def test_search_pois_validates_coords(client):
    assert client.get("/pois", params={"lat": 100, "lng": 0}).status_code == 422


def test_search_pois_upstream_error_is_502(client, fake_poi):
    fake_poi.fail = True
    assert client.get("/pois", params={"lat": 40.1, "lng": -88.2}).status_code == 502


def test_track_pois_by_step(client, fake_poi):
    body = client.get("/tracks/sample/pois", params={"step": 10}).json()
    assert [s["replay"]["index"] for s in body["stops"]] == [0, 10, 20, 30]
    assert len(fake_poi.calls) == 4
    assert body["truncated"] is False


def test_track_pois_by_distance(client):
    body = client.get("/tracks/sample/pois", params={"min_distance_m": 1000}).json()
    dists = [s["replay"]["cumulative_distance_m"] for s in body["stops"]]
    assert dists[0] == 0
    assert all(b - a >= 1000 for a, b in zip(dists, dists[1:]))


def test_track_pois_truncated(client, fake_poi):
    body = client.get("/tracks/sample/pois", params={"step": 1}).json()
    assert body["truncated"] is True
    assert len(body["stops"]) == 20

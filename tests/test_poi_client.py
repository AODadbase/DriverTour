import asyncio

import httpx
import pytest
import respx

from app.models.schemas import GPSPoint
from app.services.poi_client import MapboxPOIClient, POIClientError, feature_to_poi

BASE = "https://api.mapbox.com/search/searchbox/v1"
CENTER = GPSPoint(lat=40.1106, lng=-88.2073)


def feature(mapbox_id, name, lat, lng, **extra_props):
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lng, lat]},
        "properties": {
            "mapbox_id": mapbox_id,
            "name": name,
            "full_address": f"{name} St, Urbana, IL",
            "poi_category_ids": ["cafe", "food"],
            "coordinates": {"latitude": lat, "longitude": lng},
            **extra_props,
        },
    }


MAPBOX_RESPONSE = {
    "type": "FeatureCollection",
    "features": [
        feature("poi.far", "Far Cafe", 40.1150, -88.2073),  # ~490 m
        feature("poi.near", "Example Cafe", 40.1110, -88.2080),  # ~74 m
        feature("poi.out", "Out Of Range", 40.1300, -88.2073),  # ~2.2 km，应被过滤
    ],
}


def run(coro):
    return asyncio.run(coro)


async def search(**kwargs):
    async with httpx.AsyncClient() as http:
        client = MapboxPOIClient(access_token=kwargs.pop("token", "tok"), http_client=http, base_url=BASE)
        return await client.search_nearby(CENTER, **kwargs)


@respx.mock
def test_search_maps_fields_filters_and_sorts():
    route = respx.get(f"{BASE}/category/cafe").mock(return_value=httpx.Response(200, json=MAPBOX_RESPONSE))

    pois = run(search(radius_m=500, category="cafe"))

    assert [p.id for p in pois] == ["poi.near", "poi.far"]
    near = pois[0]
    assert near.name == "Example Cafe"
    assert near.category == "cafe"
    assert (near.lat, near.lng) == (40.1110, -88.2080)
    assert near.address == "Example Cafe St, Urbana, IL"
    assert near.distance_m == pytest.approx(74.3, abs=0.1)

    params = route.calls.last.request.url.params
    assert params["proximity"] == "-88.2073,40.1106"  # lng 在前
    assert params["access_token"] == "tok"
    min_lng, min_lat, max_lng, max_lat = map(float, params["bbox"].split(","))
    assert min_lng < CENTER.lng < max_lng and min_lat < CENTER.lat < max_lat


@respx.mock
def test_uses_default_category():
    route = respx.get(f"{BASE}/category/restaurant").mock(return_value=httpx.Response(200, json={"features": []}))
    assert run(search(radius_m=500)) == []
    assert route.called


@respx.mock
def test_http_error_raises_without_leaking_token():
    respx.get(f"{BASE}/category/cafe").mock(return_value=httpx.Response(401, json={"message": "Not Authorized"}))
    with pytest.raises(POIClientError) as exc:
        run(search(radius_m=500, category="cafe", token="secret-token"))
    assert "401" in str(exc.value)
    assert "secret-token" not in str(exc.value)


def test_missing_token_raises():
    with pytest.raises(POIClientError):
        run(search(radius_m=500, token=""))


def test_feature_falls_back_to_geometry_and_skips_incomplete():
    f = feature("poi.x", "X", 40.1110, -88.2080)
    del f["properties"]["coordinates"]
    poi = feature_to_poi(f, CENTER)
    assert (poi.lat, poi.lng) == (40.1110, -88.2080)
    assert poi.category == "cafe"

    assert feature_to_poi({"properties": {"name": "no coords"}}, CENTER) is None
    assert feature_to_poi(feature("", "", 40.1, -88.2), CENTER) is None

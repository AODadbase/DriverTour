import pytest

from app.models.schemas import GPSPoint
from app.services.geo import bounding_box, cumulative_distances, haversine_m, total_distance


@pytest.mark.parametrize(
    "a, b, expected_m",
    [
        # 北京 → 上海，约 1068 km
        ((39.9042, 116.4074), (31.2304, 121.4737), 1_068_000),
        # 纽约 → 洛杉矶，约 3936 km
        ((40.7128, -74.0060), (34.0522, -118.2437), 3_936_000),
    ],
)
def test_haversine_known_cities_within_1_percent(a, b, expected_m):
    assert haversine_m(*a, *b) == pytest.approx(expected_m, rel=0.01)


def test_haversine_same_point_is_zero():
    assert haversine_m(40.1, -88.2, 40.1, -88.2) == 0


def test_haversine_symmetric():
    assert haversine_m(10, 20, 30, 40) == pytest.approx(haversine_m(30, 40, 10, 20))


def test_one_degree_latitude_is_about_111km():
    assert haversine_m(0, 0, 1, 0) == pytest.approx(111_195, rel=0.001)


def test_cumulative_distances():
    pts = [GPSPoint(lat=0, lng=0), GPSPoint(lat=1, lng=0), GPSPoint(lat=2, lng=0)]
    dists = cumulative_distances(pts)
    assert dists[0] == 0
    assert dists[1] == pytest.approx(111_195, rel=0.001)
    assert dists[2] == pytest.approx(2 * dists[1])
    assert total_distance(pts) == dists[-1]


def test_total_distance_empty():
    assert total_distance([]) == 0.0


def test_bounding_box_contains_radius():
    lat, lng, r = 40.1106, -88.2073, 500
    min_lng, min_lat, max_lng, max_lat = bounding_box(lat, lng, r)
    assert min_lng < lng < max_lng and min_lat < lat < max_lat
    # 四条边到中心的距离应约等于半径
    assert haversine_m(lat, lng, max_lat, lng) == pytest.approx(r, rel=0.01)
    assert haversine_m(lat, lng, lat, max_lng) == pytest.approx(r, rel=0.01)

from datetime import datetime, timedelta, timezone

import pytest

from app.geo.bearing import HeadingTracker, angle_diff, bearing, is_ahead
from app.models.schemas import GPSPoint

ORIGIN = GPSPoint(lat=40.0, lng=-88.0)


@pytest.mark.parametrize(
    "to, expected",
    [
        (GPSPoint(lat=40.01, lng=-88.0), 0.0),  # 正北
        (GPSPoint(lat=40.0, lng=-87.99), 90.0),  # 正东
        (GPSPoint(lat=39.99, lng=-88.0), 180.0),  # 正南
        (GPSPoint(lat=40.0, lng=-88.01), 270.0),  # 正西
    ],
)
def test_bearing_cardinal_directions(to, expected):
    assert bearing(ORIGIN, to) == pytest.approx(expected, abs=0.01)


def test_bearing_northeast_is_between_0_and_90():
    assert 0 < bearing(ORIGIN, GPSPoint(lat=40.01, lng=-87.99)) < 90


def test_bearing_range_is_0_to_360():
    # 西北方向：atan2 原始结果为负，必须归一到 [0, 360)
    b = bearing(ORIGIN, GPSPoint(lat=40.01, lng=-88.01))
    assert 270 < b < 360


@pytest.mark.parametrize(
    "a, b, expected",
    [
        (350, 10, 20),  # 跨越 0°：顺时针 20°，不是 -340°
        (10, 350, -20),
        (359, 1, 2),
        (0, 180, -180),  # 正后方，归一到 [-180, 180)
        (90, 90, 0),
        (0, 360, 0),
        (720, 30, 30),
    ],
)
def test_angle_diff_wraps(a, b, expected):
    assert angle_diff(a, b) == pytest.approx(expected)


def test_heading_350_target_10_is_ahead():
    assert is_ahead(350, 10)


def test_target_directly_behind_is_not_ahead():
    assert not is_ahead(350, 170)
    assert not is_ahead(0, 180)


def test_target_at_0_vs_360_heading():
    assert is_ahead(0, 359)
    assert is_ahead(360, 1)


@pytest.mark.parametrize("target, expected", [(60, True), (60.5, False), (300, True), (299.5, False)])
def test_cone_edges(target, expected):
    # cone_deg 为单侧半角：heading 0 时前方是 [300, 360) ∪ [0, 60]
    assert is_ahead(0, target, cone_deg=60) is expected


def test_side_target_not_ahead():
    assert not is_ahead(0, 90)
    assert not is_ahead(0, 270)


def _pt(lat, lng, t):
    return GPSPoint(lat=lat, lng=lng, timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=t))


def test_tracker_computes_heading_and_speed():
    tr = HeadingTracker()
    tr.update(_pt(40.0, -88.0, 0))
    assert tr.heading is None
    tr.update(_pt(40.001, -88.0, 10))  # 向北约 111 m / 10 s
    assert tr.heading == pytest.approx(0, abs=0.01)
    assert tr.speed_mps == pytest.approx(11.1, rel=0.01)


def test_tracker_keeps_last_heading_when_slow():
    tr = HeadingTracker()
    tr.update(_pt(40.0, -88.0, 0))
    tr.update(_pt(40.001, -88.0, 10))  # 向北行驶
    tr.update(_pt(40.000995, -88.000005, 20))  # 停车抖动：向西南挪了不到 1 m
    assert tr.speed_mps < 2
    assert tr.heading == pytest.approx(0, abs=0.01)


def test_tracker_without_timestamps_still_tracks_heading():
    tr = HeadingTracker()
    tr.update(GPSPoint(lat=40.0, lng=-88.0))
    tr.update(GPSPoint(lat=40.0, lng=-87.999))
    assert tr.heading == pytest.approx(90, abs=0.01)
    assert tr.speed_mps == 0

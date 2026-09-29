import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.models.schemas import GPSPoint, Track
from app.services.replayer import iter_replay, replay, select_query_points

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def make_track(n=5, dt=10):
    points = [GPSPoint(lat=40 + i * 0.001, lng=-88, timestamp=T0 + timedelta(seconds=i * dt)) for i in range(n)]
    return Track(id="t", points=points, total_distance_m=0)


def test_iter_replay_offsets_scaled_by_speed():
    offsets = [rp.offset_s for rp in iter_replay(make_track(), speed=10)]
    assert offsets == pytest.approx([0, 1, 2, 3, 4])


def test_iter_replay_rejects_non_positive_speed():
    with pytest.raises(ValueError):
        list(iter_replay(make_track(), speed=0))


def test_iter_replay_missing_timestamp_counts_as_zero():
    track = make_track(3)
    track.points[1].timestamp = None
    assert [rp.offset_s for rp in iter_replay(track)] == [0, 0, 0]


def test_async_replay_sleeps_between_points():
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)

    async def run():
        return [rp.index async for rp in replay(make_track(), speed=5, sleep=fake_sleep)]

    assert asyncio.run(run()) == [0, 1, 2, 3, 4]
    assert sleeps == pytest.approx([2, 2, 2, 2])


def test_select_by_step():
    rps = list(iter_replay(make_track(10)))
    assert [rp.index for rp in select_query_points(rps, step=4)] == [0, 4, 8]


def test_select_by_distance():
    rps = list(iter_replay(make_track(10)))  # 相邻点约 111 m
    assert [rp.index for rp in select_query_points(rps, min_distance_m=300)] == [0, 3, 6, 9]


def test_select_empty():
    assert select_query_points([], step=3) == []

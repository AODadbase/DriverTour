from pathlib import Path

import pytest

from app.services.gpx_parser import GPXParseError, parse_gpx, parse_gpx_file, parse_gpx_points

SAMPLE = Path(__file__).resolve().parent.parent / "data" / "sample.gpx"

UNSORTED_GPX = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">
  <trk><name>unsorted</name><trkseg>
    <trkpt lat="40.0002" lon="-88.0"><time>2026-01-01T00:00:20Z</time></trkpt>
    <trkpt lat="40.0000" lon="-88.0"><time>2026-01-01T00:00:00Z</time></trkpt>
    <trkpt lat="95.0000" lon="-88.0"><time>2026-01-01T00:00:15Z</time></trkpt>
    <trkpt lat="40.0001" lon="-88.0"><time>2026-01-01T00:00:10Z</time></trkpt>
  </trkseg></trk>
</gpx>
"""


def test_sample_gpx_point_count_and_order():
    track = parse_gpx_file(SAMPLE, track_id="t")
    assert len(track.points) == 38
    times = [p.timestamp for p in track.points]
    assert all(t is not None for t in times)
    assert times == sorted(times)
    assert 3_000 < track.total_distance_m < 5_000
    assert track.name == "Champaign to Urbana drive"


def test_sorts_by_timestamp_and_drops_invalid_coords():
    points = parse_gpx_points(UNSORTED_GPX)
    assert [p.lat for p in points] == [40.0, 40.0001, 40.0002]


def test_parse_gpx_builds_track():
    track = parse_gpx(UNSORTED_GPX.encode(), track_id="abc")
    assert track.id == "abc"
    assert track.name == "unsorted"
    assert track.total_distance_m == pytest.approx(22.2, abs=0.5)


def test_keeps_file_order_when_timestamps_missing():
    gpx = """<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>
      <trkpt lat="1" lon="0"/><trkpt lat="0" lon="0"><time>2026-01-01T00:00:00Z</time></trkpt>
    </trkseg></trk></gpx>"""
    assert [p.lat for p in parse_gpx_points(gpx)] == [1, 0]


@pytest.mark.parametrize(
    "content",
    [
        "not xml at all",
        '<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1"></gpx>',
    ],
)
def test_invalid_gpx_raises(content):
    with pytest.raises(GPXParseError):
        parse_gpx_points(content)

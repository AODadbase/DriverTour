"""读取并解析 GPX 文件，输出按时间排序的 GPS 点序列。"""

from pathlib import Path
from typing import List, Optional, Union

import gpxpy
import gpxpy.gpx
from pydantic import ValidationError

from app.models.schemas import GPSPoint, Track
from app.services.geo import total_distance


class GPXParseError(ValueError):
    pass


def _load(content: Union[str, bytes]) -> gpxpy.gpx.GPX:
    if isinstance(content, bytes):
        try:
            content = content.decode("utf-8-sig")
        except UnicodeDecodeError as e:
            raise GPXParseError("GPX file is not valid UTF-8") from e
    try:
        return gpxpy.parse(content)
    except gpxpy.gpx.GPXException as e:
        raise GPXParseError(f"Invalid GPX: {e}") from e


def _extract_points(gpx: gpxpy.gpx.GPX) -> List[GPSPoint]:
    """遍历 tracks → segments → points，丢弃缺少/非法坐标的点，并按时间排序。"""
    points: List[GPSPoint] = []
    for track in gpx.tracks:
        for segment in track.segments:
            for p in segment.points:
                if p.latitude is None or p.longitude is None:
                    continue
                try:
                    points.append(
                        GPSPoint(lat=p.latitude, lng=p.longitude, elevation=p.elevation, timestamp=p.time)
                    )
                except ValidationError:
                    continue  # 坐标越界，视为无效点

    if not points:
        raise GPXParseError("GPX contains no valid track points")

    # 只有全部点都带时间戳时才排序；部分缺失时保持文件原顺序，避免排出错误的轨迹
    if all(p.timestamp is not None for p in points):
        points.sort(key=lambda p: p.timestamp)

    return points


def parse_gpx_points(content: Union[str, bytes]) -> List[GPSPoint]:
    return _extract_points(_load(content))


def parse_gpx(content: Union[str, bytes], track_id: str, name: Optional[str] = None) -> Track:
    gpx = _load(content)
    points = _extract_points(gpx)
    if name is None:
        name = (gpx.tracks[0].name if gpx.tracks else None) or gpx.name
    return Track(id=track_id, name=name, points=points, total_distance_m=total_distance(points))


def parse_gpx_file(path: Union[str, Path], track_id: str) -> Track:
    return parse_gpx(Path(path).read_bytes(), track_id=track_id)

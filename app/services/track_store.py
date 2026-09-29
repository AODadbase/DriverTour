"""内存中的轨迹存储（本周不做数据库持久化，重启即丢失）。"""

import uuid
from typing import Dict, Optional

from app.models.schemas import Track


class TrackStore:
    def __init__(self) -> None:
        self._tracks: Dict[str, Track] = {}

    @staticmethod
    def new_id() -> str:
        return uuid.uuid4().hex[:12]

    def add(self, track: Track) -> Track:
        self._tracks[track.id] = track
        return track

    def get(self, track_id: str) -> Optional[Track]:
        return self._tracks.get(track_id)

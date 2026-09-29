from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class GPSPoint(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)
    elevation: Optional[float] = None
    timestamp: Optional[datetime] = None


class Track(BaseModel):
    id: str
    name: Optional[str] = None
    points: List[GPSPoint]
    total_distance_m: float


class POI(BaseModel):
    id: str
    name: str
    category: Optional[str] = None
    lat: float
    lng: float
    address: Optional[str] = None
    distance_m: Optional[float] = None 


class POISearchResponse(BaseModel):
    center: GPSPoint
    radius_m: int
    results: List[POI]


class ReplayPoint(BaseModel):
    index: int
    point: GPSPoint
    cumulative_distance_m: float
    offset_s: float


class ReplayResponse(BaseModel):
    track_id: str
    speed: float
    duration_s: float
    points: List[ReplayPoint]


class TrackPOIStop(BaseModel):
    replay: ReplayPoint
    pois: POISearchResponse


class TrackPOIResponse(BaseModel):
    track_id: str
    stops: List[TrackPOIStop]
    truncated: bool = False  

from typing import Any

from pydantic import BaseModel, Field


class SpatialLocation(BaseModel):
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    village: str | None = None
    district: str | None = None
    state: str | None = None


class SpatialResult(BaseModel):
    location: SpatialLocation
    administrative_boundary: dict[str, Any] | None = None
    nearby_features: list[dict[str, Any]] = Field(default_factory=list)
    map_data: dict[str, Any] = Field(
        default_factory=lambda: {"type": "FeatureCollection", "features": []}
    )
    source: str = "local"

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio
from pyproj import Transformer


@dataclass(frozen=True, slots=True)
class ElevationResult:
    latitude: float
    longitude: float
    elevation_m: float
    elevation_risk: float
    source: str
    dataset: str
    resolution_x: float
    resolution_y: float


class ElevationAdapter:
    """Sample elevation from a local SRTM DEM and normalize it to 0..1 risk."""

    def __init__(
        self,
        raster_path: str | Path,
        *,
        low_elevation_m: float = 0.0,
        high_elevation_m: float = 100.0,
    ) -> None:
        self.raster_path = Path(raster_path)
        if not self.raster_path.exists():
            raise FileNotFoundError(f"SRTM raster not found: {self.raster_path}")
        if high_elevation_m <= low_elevation_m:
            raise ValueError("high_elevation_m must be greater than low_elevation_m")
        self.low_elevation_m = low_elevation_m
        self.high_elevation_m = high_elevation_m

    def sample(self, latitude: float, longitude: float) -> ElevationResult:
        with rasterio.open(self.raster_path) as src:
            if src.crs is None:
                raise ValueError("SRTM raster does not contain a CRS.")

            transformer = Transformer.from_crs("EPSG:4326", src.crs, always_xy=True)
            x, y = transformer.transform(longitude, latitude)

            if not (
                src.bounds.left <= x <= src.bounds.right
                and src.bounds.bottom <= y <= src.bounds.top
            ):
                raise ValueError("Requested location is outside the SRTM raster bounds.")

            sampled = next(src.sample([(x, y)], masked=True))
            value = sampled[0]

            if np.ma.is_masked(value):
                raise ValueError("SRTM elevation is NoData at the requested location.")

            elevation_m = float(value)
            if not np.isfinite(elevation_m):
                raise ValueError("SRTM elevation is not finite at the requested location.")

            return ElevationResult(
                latitude=latitude,
                longitude=longitude,
                elevation_m=round(elevation_m, 3),
                elevation_risk=round(self._elevation_risk(elevation_m), 4),
                source="SRTM",
                dataset=self.raster_path.name,
                resolution_x=float(src.res[0]),
                resolution_y=float(src.res[1]),
            )

    def _elevation_risk(self, elevation_m: float) -> float:
        if elevation_m <= self.low_elevation_m:
            return 1.0
        if elevation_m >= self.high_elevation_m:
            return 0.0
        normalized = (elevation_m - self.low_elevation_m) / (
            self.high_elevation_m - self.low_elevation_m
        )
        return max(0.0, min(1.0, 1.0 - normalized))

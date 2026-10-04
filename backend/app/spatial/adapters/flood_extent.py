from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.crs import CRS
from rasterio.transform import rowcol
from rasterio.warp import Resampling, calculate_default_transform, reproject


@dataclass(frozen=True, slots=True)
class FloodExtentResult:
    latitude: float
    longitude: float
    flood_extent_value: float
    flood_extent_risk: float
    flooded_area_sq_km: float
    source: str
    dataset: str
    resolution_x: float
    resolution_y: float


class FloodExtentAdapter:
    """
    Sample Sentinel-1 flood-extent raster and calculate flooded area.

    The raster is expected to contain:
        0 = non-flooded
        1 = flooded

    Flooded area is calculated in a projected CRS so that the
    result is expressed correctly in square kilometres.
    """

    def __init__(
        self,
        raster_path: str | Path,
        *,
        projected_crs: str = "EPSG:6933",
    ) -> None:
        self.raster_path = Path(raster_path)

        if not self.raster_path.exists():
            raise FileNotFoundError(
                f"Flood extent raster not found: {self.raster_path}"
            )

        self.projected_crs = CRS.from_string(projected_crs)

    def sample(
        self,
        latitude: float,
        longitude: float,
    ) -> FloodExtentResult:
        with rasterio.open(self.raster_path) as src:
            if src.crs is None:
                raise ValueError(
                    "Flood extent raster does not contain a CRS."
                )

            # ---------------------------------------------------------
            # 1. Transform WGS84 coordinates into raster CRS
            # ---------------------------------------------------------
            transformer = Transformer.from_crs(
                "EPSG:4326",
                src.crs,
                always_xy=True,
            )

            x, y = transformer.transform(
                longitude,
                latitude,
            )

            # ---------------------------------------------------------
            # 2. Check requested location against raster bounds
            # ---------------------------------------------------------
            if not (
                src.bounds.left <= x <= src.bounds.right
                and src.bounds.bottom <= y <= src.bounds.top
            ):
                raise ValueError(
                    "Requested location is outside the flood extent "
                    "raster bounds."
                )

            # ---------------------------------------------------------
            # 3. Sample flood value at requested location
            # ---------------------------------------------------------
            sampled = next(
                src.sample(
                    [(x, y)],
                    masked=True,
                )
            )

            value = sampled[0]

            if np.ma.is_masked(value):
                raise ValueError(
                    "Flood extent raster contains NoData at the "
                    "requested location."
                )

            flood_extent_value = float(value)

            if not np.isfinite(flood_extent_value):
                raise ValueError(
                    "Flood extent value is not finite at the "
                    "requested location."
                )

            # ---------------------------------------------------------
            # 4. Convert flood value into risk
            #
            # 0 -> no flood risk
            # 1 -> maximum flood risk
            #
            # Values between 0 and 1 are also supported.
            # ---------------------------------------------------------
            flood_extent_risk = self._flood_extent_risk(
                flood_extent_value
            )

            # ---------------------------------------------------------
            # 5. Calculate total flooded area correctly
            # ---------------------------------------------------------
            flooded_area_sq_km = self._calculate_flooded_area_sq_km()

            return FloodExtentResult(
                latitude=latitude,
                longitude=longitude,
                flood_extent_value=round(
                    flood_extent_value,
                    4,
                ),
                flood_extent_risk=round(
                    flood_extent_risk,
                    4,
                ),
                flooded_area_sq_km=round(
                    flooded_area_sq_km,
                    4,
                ),
                source="Sentinel-1",
                dataset=self.raster_path.name,
                resolution_x=float(src.res[0]),
                resolution_y=float(src.res[1]),
            )

    def _flood_extent_risk(
        self,
        flood_extent_value: float,
    ) -> float:
        """
        Normalize flood extent value to 0..1.

        0 = not flooded
        1 = flooded
        """

        if flood_extent_value <= 0:
            return 0.0

        if flood_extent_value >= 1:
            return 1.0

        return max(
            0.0,
            min(
                1.0,
                flood_extent_value,
            ),
        )

    def _calculate_flooded_area_sq_km(self) -> float:
        """
        Reproject the flood raster to an equal-area/projected CRS
        and calculate the total area of pixels classified as flooded.

        EPSG:6933 is used so that pixel dimensions are in metres.
        """

        with rasterio.open(self.raster_path) as src:
            if src.crs is None:
                raise ValueError(
                    "Flood extent raster does not contain a CRS."
                )

            transform, width, height = calculate_default_transform(
                src.crs,
                self.projected_crs,
                src.width,
                src.height,
                *src.bounds,
            )

            destination = np.zeros(
                (height, width),
                dtype=np.uint8,
            )

            reproject(
                source=rasterio.band(src, 1),
                destination=destination,
                src_transform=src.transform,
                src_crs=src.crs,
                dst_transform=transform,
                dst_crs=self.projected_crs,
                resampling=Resampling.nearest,
            )

            # Sentinel-1 flood mask:
            # 1 = flooded
            # 0 = non-flooded
            flooded_pixels = int(
                np.count_nonzero(destination == 1)
            )

            pixel_area_sq_m = abs(
                transform.a * transform.e
            )

            flooded_area_sq_km = (
                flooded_pixels
                * pixel_area_sq_m
                / 1_000_000
            )

            return float(flooded_area_sq_km)
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import numpy as np
import rasterio
from pyproj import Transformer

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
    Adapter for a locally stored Sentinel-1 flood extent raster.

    Expected raster values:

        0.0 -> no flood
        0.5 -> intermediate / partial flood
        1.0 -> flood
    """

    def __init__(
        self,
        raster_path: str | Path,
    ) -> None:
        self.raster_path = Path(raster_path)

        if not self.raster_path.exists():
            raise FileNotFoundError(
                f"Sentinel-1 flood extent raster not found: "
                f"{self.raster_path}"
            )

        with rasterio.open(self.raster_path) as src:
            if src.crs is None:
                raise ValueError(
                    "Sentinel-1 flood extent raster does not contain a CRS."
                )

            self._crs = src.crs
            self._resolution_x = float(src.res[0])
            self._resolution_y = float(src.res[1])
            self._bounds = src.bounds

            self._transformer = Transformer.from_crs(
                "EPSG:4326",
                src.crs,
                always_xy=True,
            )

            self._flooded_area_sq_km = (
                self._calculate_flooded_area(src)
            )

    def sample(
        self,
        latitude: float,
        longitude: float,
    ) -> FloodExtentResult:

        with rasterio.open(self.raster_path) as src:

            x, y = self._transformer.transform(
                longitude,
                latitude,
            )

            if not (
                src.bounds.left <= x <= src.bounds.right
                and src.bounds.bottom <= y <= src.bounds.top
            ):
                raise ValueError(
                    "Requested location is outside the "
                    "Sentinel-1 flood extent raster bounds."
                )

            sampled = next(
                src.sample(
                    [(x, y)],
                    masked=True,
                )
            )

            value = sampled[0]

            if np.ma.is_masked(value):
                raise ValueError(
                    "Sentinel-1 flood extent is NoData "
                    "at the requested location."
                )

            flood_extent_value = float(value)

            if not np.isfinite(flood_extent_value):
                raise ValueError(
                    "Sentinel-1 flood extent value is not finite."
                )

            flood_extent_risk = self._normalize_risk(
                flood_extent_value
            )

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
                    self._flooded_area_sq_km,
                    4,
                ),
                source="Sentinel-1",
                dataset=self.raster_path.name,
                resolution_x=self._resolution_x,
                resolution_y=self._resolution_y,
            )

    @staticmethod
    def _normalize_risk(
        value: float,
    ) -> float:
        """
        Keep flood extent risk between 0 and 1.
        """

        return max(
            0.0,
            min(
                1.0,
                value,
            ),
        )

    @staticmethod
    def _calculate_flooded_area(
        src,
    ) -> float:
        """
        Calculate approximate flooded area in square kilometres.

        The raster is in geographic coordinates (WGS84).
        Pixel dimensions are therefore converted approximately
        to metres using the latitude of the raster centre.

        Flood pixels are defined as values > 0.
        """

        data = src.read(
            1,
            masked=True,
        )

        values = np.ma.filled(
            data,
            0.0,
        )

        flooded = (
            np.isfinite(values)
            & (values > 0)
        )

        flooded_pixels = int(
            np.count_nonzero(flooded)
        )

        if flooded_pixels == 0:
            return 0.0

        # Raster centre latitude.
        center_latitude = (
            src.bounds.top + src.bounds.bottom
        ) / 2.0

        # Approximate metres per degree.
        latitude_radians = np.deg2rad(
            center_latitude
        )

        metres_per_degree_lat = (
            111_320.0
        )

        metres_per_degree_lon = (
            111_320.0
            * np.cos(latitude_radians)
        )

        pixel_width_m = (
            abs(src.res[0])
            * metres_per_degree_lon
        )

        pixel_height_m = (
            abs(src.res[1])
            * metres_per_degree_lat
        )

        pixel_area_m2 = (
            pixel_width_m
            * pixel_height_m
        )

        flooded_area_m2 = (
            flooded_pixels
            * pixel_area_m2
        )

        flooded_area_sq_km = (
            flooded_area_m2
            / 1_000_000.0
        )

        return float(
            flooded_area_sq_km
        )
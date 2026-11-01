from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import numpy as np
import rasterio
from pyproj import Transformer

@dataclass(frozen=True, slots=True)
class RainfallResult:
    latitude: float
    longitude: float
    total_rainfall_mm: float
    max_daily_rainfall_mm: float
    rainfall_risk: float
    source: str
    total_dataset: str
    max_daily_dataset: str
    resolution_x: float
    resolution_y: float
    period: str


class RainfallAdapter:
    """
    Sample rainfall from local IMERG GeoTIFF datasets.

    The current datasets represent Mumbai rainfall for July-August 2024.
    Rainfall risk is normalized from the maximum daily rainfall value.
    """

    def __init__(
        self,
        total_rainfall_path: str | Path,
        max_daily_rainfall_path: str | Path,
        *,
        low_rainfall_mm: float = 0.0,
        high_rainfall_mm: float = 200.0,
        period: str = "2024-07-01/2024-08-31",
    ) -> None:
        self.total_rainfall_path = Path(total_rainfall_path)
        self.max_daily_rainfall_path = Path(max_daily_rainfall_path)

        if not self.total_rainfall_path.exists():
            raise FileNotFoundError(
                f"Total rainfall raster not found: "
                f"{self.total_rainfall_path}"
            )

        if not self.max_daily_rainfall_path.exists():
            raise FileNotFoundError(
                f"Maximum daily rainfall raster not found: "
                f"{self.max_daily_rainfall_path}"
            )

        if high_rainfall_mm <= low_rainfall_mm:
            raise ValueError(
                "high_rainfall_mm must be greater than low_rainfall_mm"
            )

        self.low_rainfall_mm = low_rainfall_mm
        self.high_rainfall_mm = high_rainfall_mm
        self.period = period

    def sample(
        self,
        latitude: float,
        longitude: float,
    ) -> RainfallResult:
        with (
            rasterio.open(self.total_rainfall_path) as total_src,
            rasterio.open(self.max_daily_rainfall_path) as max_src,
        ):
            if total_src.crs is None:
                raise ValueError(
                    "Total rainfall raster does not contain a CRS."
                )

            if max_src.crs is None:
                raise ValueError(
                    "Maximum daily rainfall raster does not contain a CRS."
                )

            total_value = self._sample_raster(
                total_src,
                latitude,
                longitude,
            )

            max_daily_value = self._sample_raster(
                max_src,
                latitude,
                longitude,
            )

            rainfall_risk = self._rainfall_risk(max_daily_value)

            return RainfallResult(
                latitude=latitude,
                longitude=longitude,
                total_rainfall_mm=round(total_value, 3),
                max_daily_rainfall_mm=round(max_daily_value, 3),
                rainfall_risk=round(rainfall_risk, 4),
                source="NASA GPM IMERG",
                total_dataset=self.total_rainfall_path.name,
                max_daily_dataset=self.max_daily_rainfall_path.name,
                resolution_x=float(total_src.res[0]),
                resolution_y=float(total_src.res[1]),
                period=self.period,
            )

    @staticmethod
    def _sample_raster(
        src: rasterio.io.DatasetReader,
        latitude: float,
        longitude: float,
    ) -> float:
        transformer = Transformer.from_crs(
            "EPSG:4326",
            src.crs,
            always_xy=True,
        )

        x, y = transformer.transform(longitude, latitude)

        if not (
            src.bounds.left <= x <= src.bounds.right
            and src.bounds.bottom <= y <= src.bounds.top
        ):
            raise ValueError(
                "Requested location is outside the rainfall raster bounds."
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
                "Rainfall value is NoData at the requested location."
            )

        rainfall_mm = float(value)

        if not np.isfinite(rainfall_mm):
            raise ValueError(
                "Rainfall value is not finite at the requested location."
            )

        return rainfall_mm

    def _rainfall_risk(
        self,
        max_daily_rainfall_mm: float,
    ) -> float:
        if max_daily_rainfall_mm <= self.low_rainfall_mm:
            return 0.0

        if max_daily_rainfall_mm >= self.high_rainfall_mm:
            return 1.0

        normalized = (
            max_daily_rainfall_mm - self.low_rainfall_mm
        ) / (
            self.high_rainfall_mm - self.low_rainfall_mm
        )

        return max(
            0.0,
            min(1.0, normalized),
        )
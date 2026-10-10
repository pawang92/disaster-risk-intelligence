from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio
from pyproj import Transformer


@dataclass(frozen=True, slots=True)
class HistoricalFloodResult:
    latitude: float
    longitude: float

    flood_frequency: float
    flood_presence: float
    maximum_flood_duration_days: float
    maximum_flood_extent: float

    frequency_risk: float
    presence_risk: float
    duration_risk: float
    extent_risk: float

    historical_flood_risk: float

    source: str
    frequency_dataset: str
    presence_dataset: str
    duration_dataset: str
    extent_dataset: str


class HistoricalFloodAdapter:
    """Sample historical flood indicators from local raster datasets.

    Expected datasets:

    - Historical flood frequency: 0..10 events
    - Historical flood presence: 0..1
    - Maximum historical flood duration: 0..15 days
    - Maximum historical flood extent: 0..1

    All indicators are normalized to 0..1 and combined into a
    deterministic historical flood risk score.
    """

    FREQUENCY_MAX = 10.0
    DURATION_MAX_DAYS = 15.0

    FREQUENCY_WEIGHT = 0.25
    PRESENCE_WEIGHT = 0.25
    DURATION_WEIGHT = 0.25
    EXTENT_WEIGHT = 0.25

    def __init__(
        self,
        frequency_path: str | Path,
        presence_path: str | Path,
        duration_path: str | Path,
        extent_path: str | Path,
    ) -> None:
        self.frequency_path = Path(frequency_path)
        self.presence_path = Path(presence_path)
        self.duration_path = Path(duration_path)
        self.extent_path = Path(extent_path)

        for path, name in (
            (self.frequency_path, "frequency"),
            (self.presence_path, "presence"),
            (self.duration_path, "duration"),
            (self.extent_path, "extent"),
        ):
            if not path.exists():
                raise FileNotFoundError(
                    f"Historical flood {name} raster not found: {path}"
                )

    def sample(
        self,
        latitude: float,
        longitude: float,
    ) -> HistoricalFloodResult:
        frequency = self._sample_raster(
            self.frequency_path,
            latitude,
            longitude,
        )

        presence = self._sample_raster(
            self.presence_path,
            latitude,
            longitude,
        )

        duration = self._sample_raster(
            self.duration_path,
            latitude,
            longitude,
        )

        extent = self._sample_raster(
            self.extent_path,
            latitude,
            longitude,
        )

        frequency_value = float(frequency)
        presence_value = float(presence)
        duration_value = float(duration)
        extent_value = float(extent)

        frequency_risk = self._normalize(
            frequency_value,
            self.FREQUENCY_MAX,
        )

        presence_risk = self._normalize_binary(presence_value)

        duration_risk = self._normalize(
            duration_value,
            self.DURATION_MAX_DAYS,
        )

        extent_risk = self._normalize_binary(extent_value)

        historical_flood_risk = round(
            (
                frequency_risk * self.FREQUENCY_WEIGHT
                + presence_risk * self.PRESENCE_WEIGHT
                + duration_risk * self.DURATION_WEIGHT
                + extent_risk * self.EXTENT_WEIGHT
            ),
            4,
        )

        return HistoricalFloodResult(
            latitude=latitude,
            longitude=longitude,
            flood_frequency=round(frequency_value, 3),
            flood_presence=round(presence_value, 3),
            maximum_flood_duration_days=round(duration_value, 3),
            maximum_flood_extent=round(extent_value, 3),
            frequency_risk=round(frequency_risk, 4),
            presence_risk=round(presence_risk, 4),
            duration_risk=round(duration_risk, 4),
            extent_risk=round(extent_risk, 4),
            historical_flood_risk=historical_flood_risk,
            source="local_historical_flood_rasters",
            frequency_dataset=self.frequency_path.name,
            presence_dataset=self.presence_path.name,
            duration_dataset=self.duration_path.name,
            extent_dataset=self.extent_path.name,
        )

    @staticmethod
    def _normalize(value: float, maximum: float) -> float:
        if not np.isfinite(value):
            raise ValueError("Historical flood raster value is not finite.")

        if maximum <= 0:
            raise ValueError("Normalization maximum must be greater than zero.")

        return max(0.0, min(1.0, value / maximum))

    @staticmethod
    def _normalize_binary(value: float) -> float:
        if not np.isfinite(value):
            raise ValueError("Historical flood raster value is not finite.")

        if value <= 0:
            return 0.0

        if value >= 1:
            return 1.0

        return float(value)

    @staticmethod
    def _sample_raster(
        raster_path: Path,
        latitude: float,
        longitude: float,
    ) -> float:
        with rasterio.open(raster_path) as src:
            if src.crs is None:
                raise ValueError(
                    f"Historical flood raster does not contain a CRS: "
                    f"{raster_path}"
                )

            transformer = Transformer.from_crs(
                "EPSG:4326",
                src.crs,
                always_xy=True,
            )

            x, y = transformer.transform(
                longitude,
                latitude,
            )

            if not (
                src.bounds.left <= x <= src.bounds.right
                and src.bounds.bottom <= y <= src.bounds.top
            ):
                raise ValueError(
                    "Requested location is outside the historical flood "
                    f"raster bounds: {raster_path.name}"
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
                    "Historical flood raster contains NoData at the "
                    f"requested location: {raster_path.name}"
                )

            value = float(value)

            if not np.isfinite(value):
                raise ValueError(
                    "Historical flood raster value is not finite: "
                    f"{raster_path.name}"
                )

            return value
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
from pyproj import Transformer
from shapely.geometry import Point
from shapely.ops import unary_union


@dataclass(frozen=True, slots=True)
class RiverProximityResult:
    latitude: float
    longitude: float
    distance_to_river_m: float
    river_proximity_risk: float
    source: str
    dataset: str


class RiverProximityAdapter:
    """Calculate river proximity risk from a local river vector dataset.

    The input vector dataset is expected to contain river/stream geometries
    with a valid CRS. Distance is calculated in a metric CRS so geographic
    longitude/latitude degrees are never treated as metres.
    """

    def __init__(
        self,
        vector_path: str | Path,
        *,
        metric_crs: str = "EPSG:6933",
        near_distance_m: float = 500.0,
        far_distance_m: float = 5000.0,
    ) -> None:
        self.vector_path = Path(vector_path)

        if not self.vector_path.exists():
            raise FileNotFoundError(
                f"River dataset not found: {self.vector_path}"
            )

        if near_distance_m < 0:
            raise ValueError("near_distance_m must be non-negative")

        if far_distance_m <= near_distance_m:
            raise ValueError(
                "far_distance_m must be greater than near_distance_m"
            )

        self.metric_crs = metric_crs
        self.near_distance_m = float(near_distance_m)
        self.far_distance_m = float(far_distance_m)

        gdf = gpd.read_file(self.vector_path)

        if gdf.empty:
            raise ValueError("River dataset contains no features.")

        if gdf.crs is None:
            raise ValueError("River dataset does not contain a CRS.")

        geometry = gdf.geometry.dropna()
        if geometry.empty:
            raise ValueError("River dataset contains no valid geometries.")

        metric_gdf = gdf.loc[geometry.index].to_crs(self.metric_crs)
        self._river_geometry = unary_union(
            [geom for geom in metric_gdf.geometry if not geom.is_empty]
        )

        if self._river_geometry.is_empty:
            raise ValueError("River dataset contains no non-empty geometries.")

        self._transformer = Transformer.from_crs(
            "EPSG:4326",
            self.metric_crs,
            always_xy=True,
        )

    def sample(
        self,
        latitude: float,
        longitude: float,
    ) -> RiverProximityResult:
        x, y = self._transformer.transform(longitude, latitude)
        point = Point(x, y)

        distance_m = float(point.distance(self._river_geometry))
        risk = self._normalize_risk(distance_m)

        return RiverProximityResult(
            latitude=latitude,
            longitude=longitude,
            distance_to_river_m=round(distance_m, 3),
            river_proximity_risk=round(risk, 4),
            source="local_river_vector",
            dataset=self.vector_path.name,
        )

    def _normalize_risk(self, distance_m: float) -> float:
        if distance_m <= self.near_distance_m:
            return 1.0

        if distance_m >= self.far_distance_m:
            return 0.0

        normalized = (
            distance_m - self.near_distance_m
        ) / (
            self.far_distance_m - self.near_distance_m
        )

        return max(0.0, min(1.0, 1.0 - normalized))

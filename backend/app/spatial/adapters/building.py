from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import rasterio
from rasterio.features import shapes
from shapely.geometry import shape
from shapely.ops import unary_union


@dataclass(frozen=True, slots=True)
class BuildingExposureResult:
    """Building exposure derived from building footprints and a flood mask."""

    buildings_at_risk: int
    total_buildings_in_analysis_area: int
    affected_building_percentage: float
    source: str
    building_dataset: str
    flood_mask_dataset: str


class BuildingExposureAdapter:
    """
    Estimate building exposure to a flood extent.

    Building footprints are intersected with polygons generated from the
    binary/continuous flood raster. A building is considered affected when
    its footprint has a non-zero geometric intersection with the flood area.

    The analysis area is the flood raster bounding box. This makes the
    percentage denominator explicit and avoids presenting a bounding-box
    percentage as an administrative-area statistic.
    """

    def __init__(
        self,
        building_path: str | Path,
        flood_mask_path: str | Path,
        *,
        metric_crs: str = "EPSG:6933",
    ) -> None:
        self.building_path = Path(building_path)
        self.flood_mask_path = Path(flood_mask_path)
        self.metric_crs = metric_crs

        if not self.building_path.exists():
            raise FileNotFoundError(
                f"Building dataset not found: {self.building_path}"
            )

        if not self.flood_mask_path.exists():
            raise FileNotFoundError(
                f"Flood mask raster not found: {self.flood_mask_path}"
            )

    def calculate(self) -> BuildingExposureResult:
        """Calculate building footprints intersecting the flood extent."""

        buildings = gpd.read_file(self.building_path)

        if buildings.empty:
            raise ValueError("Building dataset contains no features.")

        if buildings.crs is None:
            raise ValueError("Building dataset does not contain a CRS.")

        buildings = buildings.loc[buildings.geometry.notna()].copy()
        buildings = buildings.loc[~buildings.geometry.is_empty].copy()

        if buildings.empty:
            raise ValueError("Building dataset contains no valid geometries.")

        with rasterio.open(self.flood_mask_path) as flood_src:
            if flood_src.crs is None:
                raise ValueError("Flood mask raster does not contain a CRS.")

            flood_geometry = self._flood_geometry(flood_src)

            if flood_geometry is None or flood_geometry.is_empty:
                return BuildingExposureResult(
                    buildings_at_risk=0,
                    total_buildings_in_analysis_area=0,
                    affected_building_percentage=0.0,
                    source="Building footprints + Sentinel-1",
                    building_dataset=self.building_path.name,
                    flood_mask_dataset=self.flood_mask_path.name,
                )

            buildings = buildings.to_crs(flood_src.crs)

            flood_bounds = flood_geometry.bounds
            candidates = buildings.cx[
                flood_bounds[0] : flood_bounds[2],
                flood_bounds[1] : flood_bounds[3],
            ].copy()

            if candidates.empty:
                return BuildingExposureResult(
                    buildings_at_risk=0,
                    total_buildings_in_analysis_area=0,
                    affected_building_percentage=0.0,
                    source="Building footprints + Sentinel-1",
                    building_dataset=self.building_path.name,
                    flood_mask_dataset=self.flood_mask_path.name,
                )

            # A building is in the analysis area if its footprint intersects
            # the flood bounding box, not merely if its centroid is inside it.
            analysis_bbox = gpd.GeoSeries(
                [shape({
                    "type": "Polygon",
                    "coordinates": [[
                        [flood_bounds[0], flood_bounds[1]],
                        [flood_bounds[2], flood_bounds[1]],
                        [flood_bounds[2], flood_bounds[3]],
                        [flood_bounds[0], flood_bounds[3]],
                        [flood_bounds[0], flood_bounds[1]],
                    ]],
                })],
                crs=flood_src.crs,
            ).iloc[0]

            analysis_candidates = candidates[
                candidates.geometry.intersects(analysis_bbox)
            ]

            total_buildings = int(len(analysis_candidates))

            affected = analysis_candidates[
                analysis_candidates.geometry.intersects(flood_geometry)
            ]

            buildings_at_risk = int(len(affected))

            percentage = (
                buildings_at_risk / total_buildings * 100.0
                if total_buildings > 0
                else 0.0
            )

            return BuildingExposureResult(
                buildings_at_risk=buildings_at_risk,
                total_buildings_in_analysis_area=total_buildings,
                affected_building_percentage=round(
                    max(0.0, min(100.0, percentage)),
                    2,
                ),
                source="Building footprints + Sentinel-1",
                building_dataset=self.building_path.name,
                flood_mask_dataset=self.flood_mask_path.name,
            )

    @staticmethod
    def _flood_geometry(
        flood_src: rasterio.io.DatasetReader,
    ):
        """Convert positive flood-mask pixels into a dissolved geometry."""

        mask = flood_src.read(1, masked=True)

        valid = (~mask.mask) & (mask.filled(0) > 0)

        if not valid.any():
            return None

        geometries = [
            shape(geometry)
            for geometry, value in shapes(
                mask.filled(0).astype("uint8"),
                mask=valid,
                transform=flood_src.transform,
            )
            if value > 0
        ]

        if not geometries:
            return None

        return unary_union(geometries)

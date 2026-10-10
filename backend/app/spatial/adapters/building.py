from __future__ import annotations

from dataclasses import dataclass
import re
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import psycopg2
import rasterio
from psycopg2 import sql
from rasterio.features import shapes
from shapely.geometry import box, shape
from shapely.ops import unary_union


@dataclass(frozen=True, slots=True)
class BuildingExposureResult:
    """Building exposure calculated from flood extent and building footprints."""

    buildings_at_risk: int
    total_buildings_in_analysis_area: int
    affected_building_percentage: float
    source: str
    building_dataset: str
    flood_mask_dataset: str


class BuildingExposureAdapter:
    """
    Calculate flood-exposed buildings from local vector and raster files.

    A building is considered affected when its footprint intersects flooded
    pixels. The analysis-area denominator is the flood raster bounding box,
    matching the project's validated exposure definition. If the flood mask
    contains no flooded pixels, exposure is zero.
    """

    def __init__(
        self,
        building_path: str | Path,
        flood_mask_path: str | Path,
        *,
        source: str = "Building footprints + Sentinel-1",
    ) -> None:
        self.building_path = Path(building_path)
        self.flood_mask_path = Path(flood_mask_path)
        self.source = source

        if not self.building_path.exists():
            raise FileNotFoundError(
                f"Building dataset not found: {self.building_path}"
            )

        if not self.flood_mask_path.exists():
            raise FileNotFoundError(
                f"Flood mask raster not found: {self.flood_mask_path}"
            )

    def calculate(self) -> BuildingExposureResult:
        buildings = gpd.read_file(self.building_path)
        if buildings.crs is None:
            raise ValueError("Building dataset does not contain a CRS.")

        buildings = buildings[buildings.geometry.notna() & ~buildings.geometry.is_empty]
        if buildings.empty:
            return self._result(0, 0)

        with rasterio.open(self.flood_mask_path) as flood_src:
            if flood_src.crs is None:
                raise ValueError("Flood mask raster does not contain a CRS.")

            flood_data = flood_src.read(1, masked=True)
            raw_values = np.ma.getdata(flood_data)
            flooded = (~np.ma.getmaskarray(flood_data)) & (raw_values > 0)

            if not np.any(flooded):
                return self._result(0, 0)

            flood_polygons = [
                shape(geom)
                for geom, value in shapes(
                    raw_values.astype("uint8", copy=False),
                    mask=flooded,
                    transform=flood_src.transform,
                )
                if value > 0
            ]
            if not flood_polygons:
                return self._result(0, 0)

            flood_geometry = unary_union(flood_polygons)
            analysis_area = box(
                flood_src.bounds.left,
                flood_src.bounds.bottom,
                flood_src.bounds.right,
                flood_src.bounds.top,
            )
            flood_crs = flood_src.crs

        buildings = buildings.to_crs(flood_crs)
        in_analysis_area = buildings[buildings.intersects(analysis_area)]
        at_risk = in_analysis_area[in_analysis_area.intersects(flood_geometry)]

        total = int(len(in_analysis_area))
        affected = int(len(at_risk))
        return self._result(affected, total)

    def _result(
        self,
        buildings_at_risk: int,
        total_buildings_in_analysis_area: int,
    ) -> BuildingExposureResult:
        percentage = (
            round(
                buildings_at_risk / total_buildings_in_analysis_area * 100.0,
                2,
            )
            if total_buildings_in_analysis_area > 0
            else 0.0
        )
        return BuildingExposureResult(
            buildings_at_risk=buildings_at_risk,
            total_buildings_in_analysis_area=total_buildings_in_analysis_area,
            affected_building_percentage=percentage,
            source=self.source,
            building_dataset=self.building_path.name,
            flood_mask_dataset=self.flood_mask_path.name,
        )


class BuildingPostGISExposureAdapter:
    """
    Calculate flood-exposed buildings from PostGIS.

    Building footprints and the derived Sentinel-1 flood extent are stored in
    PostGIS. A building is considered affected when its footprint intersects
    the flood geometry. The analysis-area denominator is the flood extent's
    bounding box, matching the project's validated exposure definition.
    """

    _IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

    def __init__(
        self,
        database_url: str,
        *,
        building_table: str = "mumbai_building_footprints",
        flood_table: str = "mumbai_s1_flood_extent",
        source: str = "Google Open Buildings V3 + Sentinel-1",
        connect_timeout_seconds: int = 10,
    ) -> None:
        if not database_url or not database_url.strip():
            raise ValueError("database_url is required.")

        if connect_timeout_seconds <= 0:
            raise ValueError("connect_timeout_seconds must be greater than zero.")

        self.database_url = self._normalize_database_url(database_url)
        self.building_table = self._validate_identifier(
            building_table,
            "building_table",
        )
        self.flood_table = self._validate_identifier(
            flood_table,
            "flood_table",
        )
        self.source = source
        self.connect_timeout_seconds = int(connect_timeout_seconds)

    def calculate(self) -> BuildingExposureResult:
        """Calculate building exposure using a PostGIS spatial intersection."""

        query = sql.SQL(
            """
            WITH flood_analysis_area AS (
                SELECT
                    ST_Envelope(ST_Union(f.geom)) AS geom
                FROM {flood_table} AS f
            ),
            metrics AS (
                SELECT
                    COUNT(*) AS total_buildings_in_analysis_area,
                    COUNT(*) FILTER (
                        WHERE EXISTS (
                            SELECT 1
                            FROM {flood_table} AS f
                            WHERE ST_Intersects(b.geom, f.geom)
                        )
                    ) AS buildings_at_risk
                FROM {building_table} AS b
                CROSS JOIN flood_analysis_area AS a
                WHERE a.geom IS NOT NULL
                  AND ST_Intersects(b.geom, a.geom)
            )
            SELECT
                total_buildings_in_analysis_area,
                buildings_at_risk,
                CASE
                    WHEN total_buildings_in_analysis_area > 0
                    THEN ROUND(
                        (
                            buildings_at_risk::numeric
                            / total_buildings_in_analysis_area::numeric
                        ) * 100,
                        4
                    )
                    ELSE 0
                END AS affected_building_percentage
            FROM metrics;
            """
        ).format(
            building_table=sql.Identifier(self.building_table),
            flood_table=sql.Identifier(self.flood_table),
        )

        try:
            with psycopg2.connect(
                self.database_url,
                connect_timeout=self.connect_timeout_seconds,
            ) as connection:
                with connection.cursor() as cursor:
                    self._validate_spatial_reference_system(
                        cursor,
                    )
                    cursor.execute(query)
                    row = cursor.fetchone()
        except psycopg2.Error as exc:
            raise RuntimeError(
                "Failed to calculate building exposure from PostGIS "
                f"({self.building_table} + {self.flood_table})."
            ) from exc

        if row is None:
            raise RuntimeError("PostGIS building exposure query returned no result.")

        total_buildings, buildings_at_risk, percentage = row

        return BuildingExposureResult(
            buildings_at_risk=int(buildings_at_risk or 0),
            total_buildings_in_analysis_area=int(total_buildings or 0),
            affected_building_percentage=float(percentage or 0.0),
            source=self.source,
            building_dataset=self.building_table,
            flood_mask_dataset=self.flood_table,
        )

    def _validate_spatial_reference_system(self, cursor: Any) -> None:
        """Fail fast when building and flood layers use different SRIDs."""

        query = sql.SQL(
            """
            SELECT
                (SELECT ST_SRID(geom) FROM {building_table} WHERE geom IS NOT NULL LIMIT 1),
                (SELECT ST_SRID(geom) FROM {flood_table} WHERE geom IS NOT NULL LIMIT 1);
            """
        ).format(
            building_table=sql.Identifier(self.building_table),
            flood_table=sql.Identifier(self.flood_table),
        )

        cursor.execute(query)
        building_srid, flood_srid = cursor.fetchone()

        if building_srid is None:
            raise ValueError(
                f"Building table '{self.building_table}' contains no valid geometry."
            )

        if flood_srid is None:
            raise ValueError(
                f"Flood table '{self.flood_table}' contains no valid geometry."
            )

        if int(building_srid) != int(flood_srid):
            raise ValueError(
                "Building and flood layers must use the same CRS/SRID: "
                f"building={building_srid}, flood={flood_srid}."
            )

    @staticmethod
    def _validate_identifier(value: str, field_name: str) -> str:
        if not value or not BuildingPostGISExposureAdapter._IDENTIFIER_RE.fullmatch(
            value
        ):
            raise ValueError(
                f"{field_name} must be a simple PostgreSQL identifier: {value!r}"
            )
        return value

    @staticmethod
    def _normalize_database_url(database_url: str) -> str:
        """Normalize SQLAlchemy-style PostgreSQL URLs for psycopg2."""

        normalized = database_url.strip()

        for prefix in (
            "postgresql+psycopg2://",
            "postgresql+psycopg://",
        ):
            if normalized.startswith(prefix):
                return "postgresql://" + normalized[len(prefix):]

        return normalized

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

import psycopg2
from psycopg2 import sql


@dataclass(frozen=True, slots=True)
class BuildingExposureResult:
    """Building exposure calculated from authoritative PostGIS layers."""

    buildings_at_risk: int
    total_buildings_in_analysis_area: int
    affected_building_percentage: float
    source: str
    building_dataset: str
    flood_mask_dataset: str


class BuildingExposureAdapter:
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
                    ST_Envelope(ST_UnaryUnion(f.geom)) AS geom
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
        if not value or not BuildingExposureAdapter._IDENTIFIER_RE.fullmatch(value):
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

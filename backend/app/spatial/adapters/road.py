from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

import psycopg2
from psycopg2 import sql


@dataclass(frozen=True, slots=True)
class RoadExposureResult:
    """Road segments intersecting the mapped flood extent."""

    roads_at_risk: int
    total_road_features_in_analysis_area: int
    affected_road_percentage: float
    affected_by_class: dict[str, int]
    totals_by_class: dict[str, int]
    source: str
    road_dataset: str
    flood_dataset: str


class RoadPostGISExposureAdapter:
    """Calculate road-segment exposure using true PostGIS intersections.

    The denominator is road features intersecting the flood geometry bounding
    box. A road is affected only when it intersects the mapped flood geometry.
    This measures mapped segment exposure, not road length flooded, passability,
    or network connectivity.
    """

    _IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

    def __init__(
        self,
        database_url: str,
        *,
        road_table: str = "mumbai_suburban_roads",
        flood_table: str = "mumbai_s1_flood_extent",
        source: str = "OpenStreetMap road segments + Sentinel-1 flood extent",
        connect_timeout_seconds: int = 10,
    ) -> None:
        if not database_url or not database_url.strip():
            raise ValueError("database_url is required.")
        if connect_timeout_seconds <= 0:
            raise ValueError("connect_timeout_seconds must be greater than zero.")
        self.database_url = self._normalize_database_url(database_url)
        self.road_table = self._validate_identifier(road_table, "road_table")
        self.flood_table = self._validate_identifier(flood_table, "flood_table")
        self.source = source
        self.connect_timeout_seconds = int(connect_timeout_seconds)

    def calculate(self) -> RoadExposureResult:
        query = sql.SQL(
            """
            WITH flood_analysis_area AS (
                SELECT ST_Envelope(ST_Union(f.geom)) AS geom
                FROM {flood_table} AS f
                WHERE f.geom IS NOT NULL AND NOT ST_IsEmpty(f.geom)
            )
            SELECT
                COALESCE(r.fclass, 'unknown') AS feature_class,
                COUNT(*) AS total_features,
                COUNT(*) FILTER (
                    WHERE EXISTS (
                        SELECT 1
                        FROM {flood_table} AS f
                        WHERE f.geom IS NOT NULL
                          AND NOT ST_IsEmpty(f.geom)
                          AND ST_Intersects(r.geom, f.geom)
                    )
                ) AS affected_features
            FROM {road_table} AS r
            CROSS JOIN flood_analysis_area AS a
            WHERE r.geom IS NOT NULL
              AND NOT ST_IsEmpty(r.geom)
              AND a.geom IS NOT NULL
              AND ST_Intersects(r.geom, a.geom)
            GROUP BY COALESCE(r.fclass, 'unknown')
            ORDER BY feature_class;
            """
        ).format(
            road_table=sql.Identifier(self.road_table),
            flood_table=sql.Identifier(self.flood_table),
        )
        try:
            with psycopg2.connect(
                self.database_url,
                connect_timeout=self.connect_timeout_seconds,
            ) as connection:
                with connection.cursor() as cursor:
                    self._validate_spatial_reference_system(cursor)
                    cursor.execute(query)
                    rows = cursor.fetchall()
        except psycopg2.Error as exc:
            raise RuntimeError(
                "Failed to calculate road exposure from PostGIS "
                f"({self.road_table} + {self.flood_table})."
            ) from exc

        totals_by_class: dict[str, int] = {}
        affected_by_class: dict[str, int] = {}
        total = 0
        affected = 0
        for feature_class, total_count, affected_count in rows:
            name = str(feature_class or "unknown")
            class_total = int(total_count or 0)
            class_affected = int(affected_count or 0)
            totals_by_class[name] = class_total
            total += class_total
            affected += class_affected
            if class_affected:
                affected_by_class[name] = class_affected

        return RoadExposureResult(
            roads_at_risk=affected,
            total_road_features_in_analysis_area=total,
            affected_road_percentage=round(affected / total * 100.0, 4) if total else 0.0,
            affected_by_class=affected_by_class,
            totals_by_class=totals_by_class,
            source=self.source,
            road_dataset=self.road_table,
            flood_dataset=self.flood_table,
        )

    def _validate_spatial_reference_system(self, cursor: Any) -> None:
        query = sql.SQL(
            """
            SELECT
                (SELECT ST_SRID(geom) FROM {road_table}
                 WHERE geom IS NOT NULL AND NOT ST_IsEmpty(geom) LIMIT 1),
                (SELECT ST_SRID(geom) FROM {flood_table}
                 WHERE geom IS NOT NULL AND NOT ST_IsEmpty(geom) LIMIT 1);
            """
        ).format(
            road_table=sql.Identifier(self.road_table),
            flood_table=sql.Identifier(self.flood_table),
        )
        cursor.execute(query)
        road_srid, flood_srid = cursor.fetchone()
        if road_srid is None:
            raise ValueError(f"Road table '{self.road_table}' contains no valid geometry.")
        if flood_srid is None:
            raise ValueError(f"Flood table '{self.flood_table}' contains no valid geometry.")
        if int(road_srid) != int(flood_srid):
            raise ValueError(
                "Road and flood layers must use the same CRS/SRID: "
                f"road={road_srid}, flood={flood_srid}."
            )

    @classmethod
    def _validate_identifier(cls, value: str, field_name: str) -> str:
        if not value or not cls._IDENTIFIER_RE.fullmatch(value):
            raise ValueError(
                f"{field_name} must be a simple PostgreSQL identifier: {value!r}"
            )
        return value

    @staticmethod
    def _normalize_database_url(database_url: str) -> str:
        normalized = database_url.strip()
        for prefix in ("postgresql+psycopg2://", "postgresql+psycopg://"):
            if normalized.startswith(prefix):
                return "postgresql://" + normalized[len(prefix):]
        return normalized

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

import psycopg2
from psycopg2 import sql


@dataclass(frozen=True, slots=True)
class CriticalInfrastructureExposureResult:
    """Critical POI features exposed to the mapped flood extent."""

    critical_assets_at_risk: int
    total_critical_assets_in_analysis_area: int
    affected_critical_asset_percentage: float
    affected_by_category: dict[str, int]
    totals_by_category: dict[str, int]
    affected_percentage_by_category: dict[str, float]
    source: str
    poi_dataset: str
    flood_dataset: str


class CriticalInfrastructurePostGISExposureAdapter:
    """Count critical POIs intersecting a mapped flood extent in PostGIS.

    The denominator includes configured critical POIs intersecting the flood
    geometry's bounding box. A POI is affected only when it intersects the
    mapped flood geometry itself. Counts are feature counts, not estimates of
    service availability or operational status.
    """

    _IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
    DEFAULT_CATEGORIES = (
        "hospital",
        "clinic",
        "doctors",
        "pharmacy",
        "school",
        "kindergarten",
        "college",
        "university",
        "fire_station",
        "police",
        "shelter",
        "social_facility",
        "nursing_home",
        "community_centre",
    )

    def __init__(
        self,
        database_url: str,
        *,
        poi_table: str = "mumbai_suburban_poi",
        flood_table: str = "mumbai_s1_flood_extent",
        categories: tuple[str, ...] | list[str] | None = None,
        source: str = "OpenStreetMap critical POIs + Sentinel-1 flood extent",
        connect_timeout_seconds: int = 10,
    ) -> None:
        if not database_url or not database_url.strip():
            raise ValueError("database_url is required.")
        if connect_timeout_seconds <= 0:
            raise ValueError("connect_timeout_seconds must be greater than zero.")
        self.database_url = self._normalize_database_url(database_url)
        self.poi_table = self._validate_identifier(poi_table, "poi_table")
        self.flood_table = self._validate_identifier(flood_table, "flood_table")
        selected = tuple(categories) if categories is not None else self.DEFAULT_CATEGORIES
        if not selected:
            raise ValueError("At least one critical POI category is required.")
        if any(not isinstance(item, str) or not item.strip() for item in selected):
            raise ValueError("Critical POI categories must be non-empty strings.")
        self.categories = tuple(dict.fromkeys(item.strip().lower() for item in selected))
        self.source = source
        self.connect_timeout_seconds = int(connect_timeout_seconds)

    def calculate(self) -> CriticalInfrastructureExposureResult:
        query = sql.SQL(
            """
            WITH flood_analysis_area AS (
                SELECT ST_Envelope(ST_Union(f.geom)) AS geom
                FROM {flood_table} AS f
                WHERE f.geom IS NOT NULL AND NOT ST_IsEmpty(f.geom)
            )
            SELECT
                COALESCE(LOWER(p.fclass), 'unknown') AS category,
                COUNT(*) AS total_features,
                COUNT(*) FILTER (
                    WHERE EXISTS (
                        SELECT 1
                        FROM {flood_table} AS f
                        WHERE f.geom IS NOT NULL
                          AND NOT ST_IsEmpty(f.geom)
                          AND ST_Intersects(p.geom, f.geom)
                    )
                ) AS affected_features
            FROM {poi_table} AS p
            CROSS JOIN flood_analysis_area AS a
            WHERE p.geom IS NOT NULL
              AND NOT ST_IsEmpty(p.geom)
              AND a.geom IS NOT NULL
              AND ST_Intersects(p.geom, a.geom)
              AND LOWER(COALESCE(p.fclass, '')) = ANY(%s)
            GROUP BY COALESCE(LOWER(p.fclass), 'unknown')
            ORDER BY category;
            """
        ).format(
            poi_table=sql.Identifier(self.poi_table),
            flood_table=sql.Identifier(self.flood_table),
        )

        try:
            with psycopg2.connect(
                self.database_url,
                connect_timeout=self.connect_timeout_seconds,
            ) as connection:
                with connection.cursor() as cursor:
                    self._validate_spatial_reference_system(cursor)
                    cursor.execute(query, (list(self.categories),))
                    rows = cursor.fetchall()
        except psycopg2.Error as exc:
            raise RuntimeError(
                "Failed to calculate critical infrastructure exposure from PostGIS "
                f"({self.poi_table} + {self.flood_table})."
            ) from exc

        totals_by_category: dict[str, int] = {}
        affected_by_category: dict[str, int] = {}
        affected_percentage_by_category: dict[str, float] = {}
        total = 0
        affected = 0
        for category, total_count, affected_count in rows:
            name = str(category or "unknown")
            category_total = int(total_count or 0)
            category_affected = int(affected_count or 0)
            totals_by_category[name] = category_total
            total += category_total
            affected += category_affected
            if category_affected:
                affected_by_category[name] = category_affected
            affected_percentage_by_category[name] = (
                round(category_affected / category_total * 100.0, 4)
                if category_total
                else 0.0
            )

        return CriticalInfrastructureExposureResult(
            critical_assets_at_risk=affected,
            total_critical_assets_in_analysis_area=total,
            affected_critical_asset_percentage=(
                round(affected / total * 100.0, 4) if total else 0.0
            ),
            affected_by_category=affected_by_category,
            totals_by_category=totals_by_category,
            affected_percentage_by_category=affected_percentage_by_category,
            source=self.source,
            poi_dataset=self.poi_table,
            flood_dataset=self.flood_table,
        )

    def _validate_spatial_reference_system(self, cursor: Any) -> None:
        query = sql.SQL(
            """
            SELECT
                (SELECT ST_SRID(geom) FROM {poi_table}
                 WHERE geom IS NOT NULL AND NOT ST_IsEmpty(geom) LIMIT 1),
                (SELECT ST_SRID(geom) FROM {flood_table}
                 WHERE geom IS NOT NULL AND NOT ST_IsEmpty(geom) LIMIT 1);
            """
        ).format(
            poi_table=sql.Identifier(self.poi_table),
            flood_table=sql.Identifier(self.flood_table),
        )
        cursor.execute(query)
        poi_srid, flood_srid = cursor.fetchone()
        if poi_srid is None:
            raise ValueError(f"POI table '{self.poi_table}' contains no valid geometry.")
        if flood_srid is None:
            raise ValueError(f"Flood table '{self.flood_table}' contains no valid geometry.")
        if int(poi_srid) != int(flood_srid):
            raise ValueError(
                "POI and flood layers must use the same CRS/SRID: "
                f"poi={poi_srid}, flood={flood_srid}."
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

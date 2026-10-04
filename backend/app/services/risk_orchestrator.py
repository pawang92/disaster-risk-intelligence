from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from app.core.config import Settings
from app.domain.schemas import (
    ExposureAssessment,
    RiskAssessment,
    RiskAssessmentRequest,
    RiskAssessmentResponse,
)
from app.risk.flood import FloodRiskEngine, FloodRiskInput
from app.spatial.adapters.elevation import ElevationAdapter
from app.spatial.adapters.rainfall import RainfallAdapter
from app.spatial.adapters.flood_extent import FloodExtentAdapter
from app.spatial.engine import SpatialEngine


@dataclass(slots=True)
class RiskOrchestrator:
    """Coordinate spatial adapters, deterministic risk engines and later AI services."""

    settings: Settings
    spatial_engine: SpatialEngine | None = None
    flood_engine: FloodRiskEngine | None = None
    elevation_adapter: ElevationAdapter | None = None
    rainfall_adapter: RainfallAdapter | None = None
    flood_extent_adapter: FloodExtentAdapter | None = None

    def __post_init__(self) -> None:
        # ---------------------------------------------------------
        # Core engines
        # ---------------------------------------------------------

        if self.spatial_engine is None:
            self.spatial_engine = SpatialEngine()

        if self.flood_engine is None:
            self.flood_engine = FloodRiskEngine()

        project_root = Path(__file__).resolve().parents[3]

        # ---------------------------------------------------------
        # Elevation / SRTM adapter
        # ---------------------------------------------------------

        if self.elevation_adapter is None:
            srtm_path = (
                project_root
                / "data"
                / "dem"
                / "mumbai"
                / "srtm"
                / "srtm_mumbai.tif"
            )

            self.elevation_adapter = ElevationAdapter(
                srtm_path
            )

        # ---------------------------------------------------------
        # Rainfall / IMERG adapter
        # ---------------------------------------------------------

        if self.rainfall_adapter is None:
            total_rainfall_path = (
                project_root
                / "data"
                / "rainfall"
                / "mumbai_imerg_total_rainfall_jul_aug_2024.tif"
            )

            max_daily_rainfall_path = (
                project_root
                / "data"
                / "rainfall"
                / "mumbai_imerg_max_daily_rainfall_jul_aug_2024.tif"
            )

            self.rainfall_adapter = RainfallAdapter(
                total_rainfall_path=total_rainfall_path,
                max_daily_rainfall_path=max_daily_rainfall_path,
            )

        # ---------------------------------------------------------
        # Flood extent / Sentinel-1 adapter
        # ---------------------------------------------------------

        if self.flood_extent_adapter is None:
            flood_extent_path = (
                project_root
                / "data"
                / "flood_extent"
                / "mumbai_s1_flood_extent.tif"
            )

            self.flood_extent_adapter = FloodExtentAdapter(
                flood_extent_path
            )

    async def assess(
        self,
        request: RiskAssessmentRequest,
    ) -> RiskAssessmentResponse:
        request_id = str(uuid4())

        spatial = await self.spatial_engine.resolve(
            request.location
        )

        # ---------------------------------------------------------
        # Hazard validation
        # ---------------------------------------------------------

        if request.hazard.value != "flood":
            return self._unsupported_hazard_response(
                request,
                request_id,
                spatial.source,
                spatial.map_data,
            )

        # ---------------------------------------------------------
        # 1. Sample real elevation data
        # ---------------------------------------------------------

        elevation = self.elevation_adapter.sample(
            latitude=request.location.latitude,
            longitude=request.location.longitude,
        )

        # ---------------------------------------------------------
        # 2. Sample real rainfall data
        # ---------------------------------------------------------

        rainfall = self.rainfall_adapter.sample(
            latitude=request.location.latitude,
            longitude=request.location.longitude,
        )

        # ---------------------------------------------------------
        # 3. Sample real Sentinel-1 flood extent data
        # ---------------------------------------------------------

        flood_extent = self.flood_extent_adapter.sample(
            latitude=request.location.latitude,
            longitude=request.location.longitude,
        )

        # ---------------------------------------------------------
        # 4. Build deterministic Flood Risk Engine input
        # ---------------------------------------------------------

        flood_inputs = FloodRiskInput(
            elevation_risk=elevation.elevation_risk,

            rainfall_risk=rainfall.rainfall_risk,

            # Real Sentinel-1 flood extent risk
            flood_extent_risk=flood_extent.flood_extent_risk,

            # These remain placeholders until their adapters
            # are implemented.
            river_proximity_risk=(
                self.settings.flood_river_proximity_risk
            ),

            historical_flood_risk=(
                self.settings.flood_historical_risk
            ),

            # Use Sentinel-1 calculated flooded area.
            affected_area_sq_km=(
                flood_extent.flooded_area_sq_km
            ),

            source_metadata={
                # -------------------------------------------------
                # Elevation metadata
                # -------------------------------------------------

                "elevation": {
                    "source": elevation.source,
                    "dataset": elevation.dataset,
                    "elevation_m": elevation.elevation_m,
                    "elevation_risk": elevation.elevation_risk,
                    "resolution_x": elevation.resolution_x,
                    "resolution_y": elevation.resolution_y,
                },

                # -------------------------------------------------
                # Rainfall metadata
                # -------------------------------------------------

                "rainfall": {
                    "source": rainfall.source,
                    "total_dataset": rainfall.total_dataset,
                    "max_daily_dataset": (
                        rainfall.max_daily_dataset
                    ),
                    "total_rainfall_mm": (
                        rainfall.total_rainfall_mm
                    ),
                    "max_daily_rainfall_mm": (
                        rainfall.max_daily_rainfall_mm
                    ),
                    "rainfall_risk": rainfall.rainfall_risk,
                    "period": rainfall.period,
                    "resolution_x": rainfall.resolution_x,
                    "resolution_y": rainfall.resolution_y,
                },

                # -------------------------------------------------
                # Sentinel-1 flood extent metadata
                # -------------------------------------------------

                "flood_extent": {
                    "source": flood_extent.source,
                    "dataset": flood_extent.dataset,
                    "flood_extent_value": (
                        flood_extent.flood_extent_value
                    ),
                    "flood_extent_risk": (
                        flood_extent.flood_extent_risk
                    ),
                    "flooded_area_sq_km": (
                        flood_extent.flooded_area_sq_km
                    ),
                    "resolution_x": (
                        flood_extent.resolution_x
                    ),
                    "resolution_y": (
                        flood_extent.resolution_y
                    ),
                },
            },
        )

        # ---------------------------------------------------------
        # 5. Calculate flood risk
        # ---------------------------------------------------------

        result = self.flood_engine.calculate(
            flood_inputs
        )

        # ---------------------------------------------------------
        # 6. Return orchestrated risk assessment
        # ---------------------------------------------------------

        return RiskAssessmentResponse(
            request_id=request_id,
            location=request.location,
            hazard=request.hazard,

            risk_assessment=RiskAssessment(
                risk_level=result.risk_level,
                risk_score=result.risk_score,
                affected_area_sq_km=(
                    result.affected_area_sq_km
                ),
                methodology_version=(
                    result.methodology_version
                ),

                inputs={
                    "hazard_score": result.hazard_score,

                    "contributing_factors": (
                        result.contributing_factors
                    ),

                    "spatial_source": spatial.source,

                    "indicator_source": "real_spatial_data",

                    # -------------------------------------------------
                    # Elevation result
                    # -------------------------------------------------

                    "elevation": {
                        "elevation_m": elevation.elevation_m,
                        "elevation_risk": (
                            elevation.elevation_risk
                        ),
                        "source": elevation.source,
                        "dataset": elevation.dataset,
                    },

                    # -------------------------------------------------
                    # Rainfall result
                    # -------------------------------------------------

                    "rainfall": {
                        "total_rainfall_mm": (
                            rainfall.total_rainfall_mm
                        ),
                        "max_daily_rainfall_mm": (
                            rainfall.max_daily_rainfall_mm
                        ),
                        "rainfall_risk": (
                            rainfall.rainfall_risk
                        ),
                        "source": rainfall.source,
                        "total_dataset": (
                            rainfall.total_dataset
                        ),
                        "max_daily_dataset": (
                            rainfall.max_daily_dataset
                        ),
                        "period": rainfall.period,
                    },

                    # -------------------------------------------------
                    # Sentinel-1 flood extent result
                    # -------------------------------------------------

                    "flood_extent": {
                        "flood_extent_value": (
                            flood_extent.flood_extent_value
                        ),
                        "flood_extent_risk": (
                            flood_extent.flood_extent_risk
                        ),
                        "flooded_area_sq_km": (
                            flood_extent.flooded_area_sq_km
                        ),
                        "source": flood_extent.source,
                        "dataset": flood_extent.dataset,
                    },
                },
            ),

            exposure=ExposureAssessment(),

            recommendations=[],

            map_data=spatial.map_data,

            explanation=(
                "Flood risk uses real SRTM elevation, "
                "NASA GPM IMERG rainfall, and Sentinel-1 "
                "flood extent data. River proximity and "
                "historical flood indicators remain "
                "configured placeholders until their "
                "adapters are connected."
            ),
        )

    @staticmethod
    def _unsupported_hazard_response(
        request,
        request_id,
        spatial_source,
        map_data,
    ):
        return RiskAssessmentResponse(
            request_id=request_id,
            location=request.location,
            hazard=request.hazard,

            risk_assessment=RiskAssessment(
                risk_level="not_implemented",
                methodology_version=None,
                inputs={
                    "status": "hazard_engine_not_connected",
                    "spatial_source": spatial_source,
                },
            ),

            exposure=None,
            recommendations=[],
            map_data=map_data,

            explanation=(
                f"The {request.hazard.value} risk engine "
                "is not implemented yet."
            ),
        )
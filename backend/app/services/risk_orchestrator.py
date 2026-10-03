from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from app.core.config import Settings
from app.domain.schemas import (
    ExposureAssessment,
    Recommendation,
    RiskAssessment,
    RiskAssessmentRequest,
    RiskAssessmentResponse,
)
from app.risk.flood import FloodRiskEngine, FloodRiskInput
from app.spatial.adapters.elevation import ElevationAdapter
from app.spatial.engine import SpatialEngine


@dataclass(slots=True)
class RiskOrchestrator:
    """Coordinate spatial adapters, deterministic risk engines and later AI services."""

    settings: Settings
    spatial_engine: SpatialEngine | None = None
    flood_engine: FloodRiskEngine | None = None
    elevation_adapter: ElevationAdapter | None = None

    def __post_init__(self) -> None:
        if self.spatial_engine is None:
            self.spatial_engine = SpatialEngine()
        if self.flood_engine is None:
            self.flood_engine = FloodRiskEngine()
        if self.elevation_adapter is None:
            project_root = Path(__file__).resolve().parents[3]
            srtm_path = project_root / "data" / "dem" / "mumbai" / "srtm" / "srtm_mumbai.tif"
            self.elevation_adapter = ElevationAdapter(srtm_path)

    async def assess(self, request: RiskAssessmentRequest) -> RiskAssessmentResponse:
        request_id = str(uuid4())
        spatial = await self.spatial_engine.resolve(request.location)

        if request.hazard.value != "flood":
            return self._unsupported_hazard_response(
                request, request_id, spatial.source, spatial.map_data
            )

        elevation = self.elevation_adapter.sample(
            latitude=request.location.latitude,
            longitude=request.location.longitude,
        )

        flood_inputs = FloodRiskInput(
            elevation_risk=elevation.elevation_risk,
            rainfall_risk=self.settings.flood_rainfall_risk,
            flood_extent_risk=self.settings.flood_extent_risk,
            river_proximity_risk=self.settings.flood_river_proximity_risk,
            historical_flood_risk=self.settings.flood_historical_risk,
            affected_area_sq_km=self.settings.flood_affected_area_sq_km,
            source_metadata={
                "elevation": {
                    "source": elevation.source,
                    "dataset": elevation.dataset,
                    "elevation_m": elevation.elevation_m,
                    "resolution_x": elevation.resolution_x,
                    "resolution_y": elevation.resolution_y,
                },
            },
        )
        result = self.flood_engine.calculate(flood_inputs)

        return RiskAssessmentResponse(
            request_id=request_id,
            location=request.location,
            hazard=request.hazard,
            risk_assessment=RiskAssessment(
                risk_level=result.risk_level,
                risk_score=result.risk_score,
                affected_area_sq_km=result.affected_area_sq_km,
                methodology_version=result.methodology_version,
                inputs={
                    "hazard_score": result.hazard_score,
                    "contributing_factors": result.contributing_factors,
                    "spatial_source": spatial.source,
                    "indicator_source": "real_spatial_data",
                    "elevation": {
                        "elevation_m": elevation.elevation_m,
                        "elevation_risk": elevation.elevation_risk,
                        "source": elevation.source,
                        "dataset": elevation.dataset,
                    },
                },
            ),
            exposure=ExposureAssessment(),
            recommendations=[],
            map_data=spatial.map_data,
            explanation=(
                "Flood risk uses the real SRTM elevation adapter. Rainfall, "
                "flood extent, river proximity, and historical flood indicators "
                "remain configured placeholders until their adapters are connected."
            ),
        )

    @staticmethod
    def _unsupported_hazard_response(request, request_id, spatial_source, map_data):
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
            explanation=f"The {request.hazard.value} risk engine is not implemented yet.",
        )

from __future__ import annotations

from dataclasses import dataclass
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
from app.spatial.engine import SpatialEngine


@dataclass(slots=True)
class RiskOrchestrator:
    """Coordinate deterministic risk engines, spatial intelligence and later AI services."""

    settings: Settings
    spatial_engine: SpatialEngine | None = None
    flood_engine: FloodRiskEngine | None = None

    def __post_init__(self) -> None:
        if self.spatial_engine is None:
            self.spatial_engine = SpatialEngine()
        if self.flood_engine is None:
            self.flood_engine = FloodRiskEngine()

    async def assess(self, request: RiskAssessmentRequest) -> RiskAssessmentResponse:
        request_id = str(uuid4())
        spatial = await self.spatial_engine.resolve(request.location)

        if request.hazard.value != "flood":
            return self._unsupported_hazard_response(request, request_id, spatial.source, spatial.map_data)

        flood_inputs = FloodRiskInput(
            elevation_risk=self.settings.flood_elevation_risk,
            rainfall_risk=self.settings.flood_rainfall_risk,
            flood_extent_risk=self.settings.flood_extent_risk,
            river_proximity_risk=self.settings.flood_river_proximity_risk,
            historical_flood_risk=self.settings.flood_historical_risk,
            affected_area_sq_km=self.settings.flood_affected_area_sq_km,
            source_metadata={"source": "local_configuration"},
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
                    "indicator_source": "local_configuration",
                },
            ),
            exposure=ExposureAssessment(),
            recommendations=[],
            map_data=spatial.map_data,
            explanation=(
                "Flood risk was calculated deterministically from the configured "
                "normalized flood indicators. Real spatial and environmental data "
                "adapters will replace these local inputs in the next phase."
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
                inputs={"status": "hazard_engine_not_connected", "spatial_source": spatial_source},
            ),
            exposure=None,
            recommendations=[],
            map_data=map_data,
            explanation=f"The {request.hazard.value} risk engine is not implemented yet.",
        )

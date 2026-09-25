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
from app.spatial.engine import SpatialEngine


@dataclass(slots=True)
class RiskOrchestrator:
    """Coordinate deterministic engines, knowledge retrieval and LLM synthesis."""

    settings: Settings
    spatial_engine: SpatialEngine | None = None

    def __post_init__(self) -> None:
        if self.spatial_engine is None:
            self.spatial_engine = SpatialEngine()

    async def assess(self, request: RiskAssessmentRequest) -> RiskAssessmentResponse:
        request_id = str(uuid4())
        spatial = await self.spatial_engine.resolve(request.location)

        return RiskAssessmentResponse(
            request_id=request_id,
            location=request.location,
            hazard=request.hazard,
            risk_assessment=RiskAssessment(
                risk_level="not_calculated",
                methodology_version=self.settings.risk_engine_version,
                inputs={
                    "status": "engine_not_connected",
                    "spatial_source": spatial.source,
                },
            ),
            exposure=ExposureAssessment(),
            recommendations=[
                Recommendation(
                    action="Risk engine and evidence services must be connected before operational recommendations are generated.",
                    priority="high",
                )
            ],
            map_data=spatial.map_data,
            explanation=(
                "Spatial resolution is connected to the Disaster Risk Intelligence "
                "orchestrator, but no deterministic risk result has been calculated yet."
            ),
        )

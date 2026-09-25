from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from app.domain.schemas import (
    ExposureAssessment,
    Recommendation,
    RiskAssessment,
    RiskAssessmentRequest,
    RiskAssessmentResponse,
)
from app.core.config import Settings


@dataclass(slots=True)
class RiskOrchestrator:
    """Coordinates deterministic engines, knowledge retrieval and LLM synthesis.

    Phase 1 intentionally exposes the contract only. Concrete spatial, risk,
    exposure, RAG and LLM adapters will be injected in later phases.
    """

    settings: Settings

    async def assess(self, request: RiskAssessmentRequest) -> RiskAssessmentResponse:
        request_id = str(uuid4())

        return RiskAssessmentResponse(
            request_id=request_id,
            location=request.location,
            hazard=request.hazard,
            risk_assessment=RiskAssessment(
                risk_level="not_calculated",
                methodology_version=self.settings.risk_engine_version,
                inputs={"status": "engine_not_connected"},
            ),
            exposure=ExposureAssessment(),
            recommendations=[
                Recommendation(
                    action="Risk engine and evidence services must be connected before operational recommendations are generated.",
                    priority="high",
                )
            ],
            explanation=(
                "The Disaster Risk Intelligence orchestration contract is active, "
                "but no deterministic risk result has been calculated yet."
            ),
        )

from fastapi import APIRouter, Depends

from app.core.config import Settings, get_settings
from app.domain.schemas import RiskAssessmentRequest, RiskAssessmentResponse
from app.services.risk_orchestrator import RiskOrchestrator

router = APIRouter(prefix="/risk", tags=["risk"])


@router.post("/assess", response_model=RiskAssessmentResponse)
async def assess_risk(
    request: RiskAssessmentRequest,
    settings: Settings = Depends(get_settings),
) -> RiskAssessmentResponse:
    """Run the Disaster Risk Intelligence orchestration contract."""
    return await RiskOrchestrator(settings).assess(request)

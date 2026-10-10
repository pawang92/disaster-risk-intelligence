from fastapi import APIRouter, Depends, HTTPException

from app.domain.schemas import RiskAssessmentRequest, RiskAssessmentResponse
from app.services.risk_orchestrator import RiskOrchestrator, get_risk_orchestrator

router = APIRouter(prefix="/risk", tags=["risk"])


@router.post("/assess", response_model=RiskAssessmentResponse)
async def assess_risk(
    request: RiskAssessmentRequest,
    orchestrator: RiskOrchestrator = Depends(get_risk_orchestrator),
) -> RiskAssessmentResponse:
    """Run the Disaster Risk Intelligence orchestration contract."""
    try:
        return await orchestrator.assess(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

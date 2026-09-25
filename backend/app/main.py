from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.risk import router as risk_router
from app.core.config import get_settings

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Backend orchestration API for Disaster Risk Intelligence.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "disaster-risk-intelligence",
        "environment": settings.environment,
    }


@app.get(f"{settings.api_prefix}/system/info", tags=["system"])
async def system_info() -> dict[str, object]:
    return {
        "service": settings.app_name,
        "version": settings.app_version,
        "default_hazard": settings.default_hazard,
        "risk_engine_version": settings.risk_engine_version,
        "llm_provider": settings.llm_provider,
        "llm_fallbacks": settings.fallback_providers,
    }


app.include_router(risk_router, prefix=settings.api_prefix)

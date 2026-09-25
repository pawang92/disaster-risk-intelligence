from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class HazardType(str, Enum):
    FLOOD = "flood"
    EARTHQUAKE = "earthquake"
    CYCLONE = "cyclone"
    LANDSLIDE = "landslide"
    DROUGHT = "drought"
    WILDFIRE = "wildfire"


class LocationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    village: str | None = Field(default=None, min_length=1, max_length=200)
    district: str | None = Field(default=None, min_length=1, max_length=200)
    state: str | None = Field(default=None, min_length=1, max_length=200)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)

    @field_validator("village", "district", "state", mode="before")
    @classmethod
    def strip_text(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value


class RiskAssessmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    location: LocationInput
    hazard: HazardType = HazardType.FLOOD
    question: str = Field(
        default="What is the disaster risk at this location and what actions should be taken?",
        min_length=5,
        max_length=2000,
    )
    include_exposure: bool = True
    include_evidence: bool = True
    include_recommendations: bool = True


class RiskAssessment(BaseModel):
    risk_level: str = "unknown"
    risk_score: float | None = Field(default=None, ge=0, le=1)
    affected_area_sq_km: float | None = Field(default=None, ge=0)
    methodology_version: str | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)


class ExposureAssessment(BaseModel):
    properties_at_risk: int | None = Field(default=None, ge=0)
    population_at_risk: int | None = Field(default=None, ge=0)
    roads_at_risk: int | None = Field(default=None, ge=0)
    critical_assets_at_risk: int | None = Field(default=None, ge=0)
    details: dict[str, Any] = Field(default_factory=dict)


class EvidenceItem(BaseModel):
    source: str
    page: int | None = Field(default=None, ge=1)
    score: float | None = None
    excerpt: str | None = None


class Recommendation(BaseModel):
    action: str
    priority: str = "medium"
    rationale: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)


class GeoJSON(BaseModel):
    type: str = "FeatureCollection"
    features: list[dict[str, Any]] = Field(default_factory=list)


class RiskAssessmentResponse(BaseModel):
    request_id: str
    location: LocationInput
    hazard: HazardType
    risk_assessment: RiskAssessment
    exposure: ExposureAssessment | None = None
    evidence: list[EvidenceItem] = Field(default_factory=list)
    recommendations: list[Recommendation] = Field(default_factory=list)
    map_data: GeoJSON = Field(default_factory=GeoJSON)
    explanation: str | None = None

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field


class FloodRiskInput(BaseModel):
    """Normalized indicators consumed by the flood risk engine.

    Values are normalized to 0..1 before scoring. They represent hazard or
    susceptibility indicators, not raw measurements. Raw data adapters will
    be added separately so the scoring logic remains deterministic and testable.
    """

    elevation_risk: float = Field(default=0.0, ge=0.0, le=1.0)
    rainfall_risk: float = Field(default=0.0, ge=0.0, le=1.0)
    flood_extent_risk: float = Field(default=0.0, ge=0.0, le=1.0)
    river_proximity_risk: float = Field(default=0.0, ge=0.0, le=1.0)
    historical_flood_risk: float = Field(default=0.0, ge=0.0, le=1.0)

    affected_area_sq_km: float | None = Field(default=None, ge=0.0)

    source_metadata: dict[str, Any] = Field(default_factory=dict)


class FloodRiskResult(BaseModel):
    hazard_score: float = Field(ge=0.0, le=1.0)
    risk_score: float = Field(ge=0.0, le=1.0)
    risk_level: str
    affected_area_sq_km: float | None = Field(default=None, ge=0.0)
    contributing_factors: list[str] = Field(default_factory=list)
    methodology_version: str


@dataclass(frozen=True, slots=True)
class FloodRiskEngine:
    """Deterministic first-version flood hazard scoring engine.

    The engine deliberately accepts normalized indicators. It does not fetch
    external data and does not use an LLM. Data acquisition/normalization is a
    separate concern and will later feed this engine from PostGIS/raster/API
    adapters.
    """

    methodology_version: str = "flood-v0.1"

    # Initial transparent weights. These are configuration for the prototype,
    # not a claim of scientific calibration. They must be validated against
    # authoritative/local flood datasets before operational use.
    elevation_weight: float = 0.20
    rainfall_weight: float = 0.25
    flood_extent_weight: float = 0.25
    river_proximity_weight: float = 0.15
    historical_flood_weight: float = 0.15

    def calculate(self, inputs: FloodRiskInput) -> FloodRiskResult:
        weighted = (
            inputs.elevation_risk * self.elevation_weight
            + inputs.rainfall_risk * self.rainfall_weight
            + inputs.flood_extent_risk * self.flood_extent_weight
            + inputs.river_proximity_risk * self.river_proximity_weight
            + inputs.historical_flood_risk * self.historical_flood_weight
        )

        hazard_score = round(max(0.0, min(1.0, weighted)), 4)
        risk_level = self._risk_level(hazard_score)
        factors = self._factors(inputs)

        return FloodRiskResult(
            hazard_score=hazard_score,
            risk_score=hazard_score,
            risk_level=risk_level,
            affected_area_sq_km=inputs.affected_area_sq_km,
            contributing_factors=factors,
            methodology_version=self.methodology_version,
        )

    @staticmethod
    def _risk_level(score: float) -> str:
        if score < 0.25:
            return "low"
        if score < 0.50:
            return "moderate"
        if score < 0.75:
            return "high"
        return "very_high"

    @staticmethod
    def _factors(inputs: FloodRiskInput) -> list[str]:
        indicators = {
            "elevation": inputs.elevation_risk,
            "rainfall": inputs.rainfall_risk,
            "flood_extent": inputs.flood_extent_risk,
            "river_proximity": inputs.river_proximity_risk,
            "historical_flood": inputs.historical_flood_risk,
        }
        return [name for name, value in indicators.items() if value >= 0.50]

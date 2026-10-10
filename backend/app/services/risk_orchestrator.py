from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

from app.core.config import Settings, get_settings
from app.domain.schemas import (
    ExposureAssessment,
    Recommendation,
    RiskAssessment,
    RiskAssessmentRequest,
    RiskAssessmentResponse,
)
from app.risk.flood import FloodRiskEngine, FloodRiskInput
from app.spatial.adapters.building import (
    BuildingExposureAdapter,
    BuildingPostGISExposureAdapter,
)
from app.spatial.adapters.railway import RailwayPostGISExposureAdapter
from app.spatial.adapters.elevation import ElevationAdapter
from app.spatial.adapters.rainfall import RainfallAdapter
from app.spatial.adapters.flood_extent import FloodExtentAdapter
from app.spatial.adapters.river_proximity import RiverProximityAdapter
from app.spatial.adapters.historical_flood import HistoricalFloodAdapter
from app.spatial.adapters.population import PopulationExposureAdapter
from app.spatial.engine import SpatialEngine


@dataclass(slots=True)
class RiskOrchestrator:
    """Coordinate spatial adapters and deterministic flood risk assessment."""

    settings: Settings
    spatial_engine: SpatialEngine | None = None
    flood_engine: FloodRiskEngine | None = None
    elevation_adapter: ElevationAdapter | None = None
    rainfall_adapter: RainfallAdapter | None = None
    flood_extent_adapter: FloodExtentAdapter | None = None
    river_proximity_adapter: RiverProximityAdapter | None = None
    historical_flood_adapter: HistoricalFloodAdapter | None = None
    population_exposure_adapter: PopulationExposureAdapter | None = None
    building_exposure_adapter: (
        BuildingExposureAdapter | BuildingPostGISExposureAdapter | None
    ) = None
    railway_exposure_adapter: RailwayPostGISExposureAdapter | None = None

    def __post_init__(self) -> None:
        if self.spatial_engine is None:
            self.spatial_engine = SpatialEngine()

        if self.flood_engine is None:
            self.flood_engine = FloodRiskEngine()

        project_root = Path(__file__).resolve().parents[3]

        if self.elevation_adapter is None:
            srtm_path = (
                project_root
                / "data"
                / "dem"
                / "mumbai"
                / "srtm"
                / "srtm_mumbai.tif"
            )
            self.elevation_adapter = ElevationAdapter(srtm_path)

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

        if self.flood_extent_adapter is None:
            flood_extent_path = (
                project_root
                / "data"
                / "flood_extent"
                / "mumbai_s1_flood_extent.tif"
            )
            self.flood_extent_adapter = FloodExtentAdapter(flood_extent_path)

        if self.river_proximity_adapter is None:
            river_path = (
                project_root
                / "data"
                / "rivers"
                / "mumbai_hydrosheds_river_network.geojson"
            )
            self.river_proximity_adapter = RiverProximityAdapter(river_path)

        if self.historical_flood_adapter is None:
            historical_flood_dir = project_root / "data" / "historical_flood"
            self.historical_flood_adapter = HistoricalFloodAdapter(
                frequency_path=(
                    historical_flood_dir
                    / "mumbai_historical_flood_frequency.tif"
                ),
                presence_path=(
                    historical_flood_dir
                    / "mumbai_historical_flood_presence.tif"
                ),
                duration_path=(
                    historical_flood_dir
                    / "mumbai_maximum_historical_flood_duration.tif"
                ),
                extent_path=(
                    historical_flood_dir
                    / "mumbai_maximum_historical_flood_extent.tif"
                ),
            )

        if self.population_exposure_adapter is None:
            population_path = (
                project_root
                / "data"
                / "population"
                / "ind_pop_2024_UC_100m_R2024A_v1.tif"
            )
            flood_extent_path = (
                project_root
                / "data"
                / "flood_extent"
                / "mumbai_s1_flood_extent.tif"
            )
            self.population_exposure_adapter = PopulationExposureAdapter(
                population_path=population_path,
                flood_mask_path=flood_extent_path,
            )

        if self.building_exposure_adapter is None:
            backend = self.settings.building_exposure_backend
            if backend == "postgis":
                self.building_exposure_adapter = BuildingPostGISExposureAdapter(
                    database_url=self.settings.postgis_url,
                    building_table="mumbai_building_footprints",
                    flood_table="mumbai_s1_flood_extent",
                )
            elif backend == "file":
                building_path = (
                    project_root
                    / "data"
                    / "buildings"
                    / "mumbai_building_footprints.geojson"
                )
                flood_extent_path = (
                    project_root
                    / "data"
                    / "flood_extent"
                    / "mumbai_s1_flood_extent.tif"
                )
                if building_path.exists() and flood_extent_path.exists():
                    self.building_exposure_adapter = BuildingExposureAdapter(
                        building_path=building_path,
                        flood_mask_path=flood_extent_path,
                    )
            elif backend != "disabled":
                raise ValueError(
                    "building_exposure_backend must be 'postgis', 'file', or 'disabled'."
                )

        if (
            self.railway_exposure_adapter is None
            and self.settings.building_exposure_backend == "postgis"
        ):
            self.railway_exposure_adapter = RailwayPostGISExposureAdapter(
                database_url=self.settings.postgis_url,
                railway_table="mumbai_suburban_railway",
                flood_table="mumbai_s1_flood_extent",
            )

    async def assess(
        self,
        request: RiskAssessmentRequest,
    ) -> RiskAssessmentResponse:
        request_id = str(uuid4())

        spatial = await self.spatial_engine.resolve(request.location)

        if request.hazard.value != "flood":
            return self._unsupported_hazard_response(
                request,
                request_id,
                spatial.source,
                spatial.map_data,
            )

        elevation = self.elevation_adapter.sample(
            latitude=request.location.latitude,
            longitude=request.location.longitude,
        )

        rainfall = self.rainfall_adapter.sample(
            latitude=request.location.latitude,
            longitude=request.location.longitude,
        )

        flood_extent = self.flood_extent_adapter.sample(
            latitude=request.location.latitude,
            longitude=request.location.longitude,
        )

        river_proximity = self.river_proximity_adapter.sample(
            latitude=request.location.latitude,
            longitude=request.location.longitude,
        )

        historical_flood = self.historical_flood_adapter.sample(
            latitude=request.location.latitude,
            longitude=request.location.longitude,
        )

        population_exposure = (
            self.population_exposure_adapter.calculate()
            if request.include_exposure
            else None
        )

        building_exposure = (
            self.building_exposure_adapter.calculate()
            if request.include_exposure and self.building_exposure_adapter is not None
            else None
        )

        railway_exposure = (
            self.railway_exposure_adapter.calculate()
            if request.include_exposure and self.railway_exposure_adapter is not None
            else None
        )

        flood_inputs = FloodRiskInput(
            elevation_risk=elevation.elevation_risk,
            rainfall_risk=rainfall.rainfall_risk,
            flood_extent_risk=flood_extent.flood_extent_risk,
            river_proximity_risk=river_proximity.river_proximity_risk,
            historical_flood_risk=historical_flood.historical_flood_risk,
            affected_area_sq_km=flood_extent.flooded_area_sq_km,
            source_metadata={
                "elevation": {
                    "source": elevation.source,
                    "dataset": elevation.dataset,
                    "elevation_m": elevation.elevation_m,
                    "elevation_risk": elevation.elevation_risk,
                    "resolution_x": elevation.resolution_x,
                    "resolution_y": elevation.resolution_y,
                },
                "rainfall": {
                    "source": rainfall.source,
                    "total_dataset": rainfall.total_dataset,
                    "max_daily_dataset": rainfall.max_daily_dataset,
                    "total_rainfall_mm": rainfall.total_rainfall_mm,
                    "max_daily_rainfall_mm": rainfall.max_daily_rainfall_mm,
                    "rainfall_risk": rainfall.rainfall_risk,
                    "period": rainfall.period,
                    "resolution_x": rainfall.resolution_x,
                    "resolution_y": rainfall.resolution_y,
                },
                "flood_extent": {
                    "source": flood_extent.source,
                    "dataset": flood_extent.dataset,
                    "flood_extent_value": flood_extent.flood_extent_value,
                    "flood_extent_risk": flood_extent.flood_extent_risk,
                    "flooded_area_sq_km": flood_extent.flooded_area_sq_km,
                    "resolution_x": flood_extent.resolution_x,
                    "resolution_y": flood_extent.resolution_y,
                },
                "river_proximity": {
                    "source": river_proximity.source,
                    "dataset": river_proximity.dataset,
                    "distance_to_river_m": river_proximity.distance_to_river_m,
                    "river_proximity_risk": river_proximity.river_proximity_risk,
                },
                "historical_flood": {
                    "source": historical_flood.source,
                    "frequency_dataset": historical_flood.frequency_dataset,
                    "presence_dataset": historical_flood.presence_dataset,
                    "duration_dataset": historical_flood.duration_dataset,
                    "extent_dataset": historical_flood.extent_dataset,
                    "flood_frequency": historical_flood.flood_frequency,
                    "flood_presence": historical_flood.flood_presence,
                    "maximum_flood_duration_days": historical_flood.maximum_flood_duration_days,
                    "maximum_flood_extent": historical_flood.maximum_flood_extent,
                    "frequency_risk": historical_flood.frequency_risk,
                    "presence_risk": historical_flood.presence_risk,
                    "duration_risk": historical_flood.duration_risk,
                    "extent_risk": historical_flood.extent_risk,
                    "historical_flood_risk": historical_flood.historical_flood_risk,
                },
                "population_exposure": (
                    {
                        "source": population_exposure.source,
                        "population_dataset": population_exposure.population_dataset,
                        "flood_mask_dataset": population_exposure.flood_mask_dataset,
                        "population_at_risk": population_exposure.population_at_risk,
                        "population_in_analysis_area": (
                            population_exposure.population_in_analysis_area
                        ),
                        "affected_population_percentage": (
                            population_exposure.affected_population_percentage
                        ),
                        "flooded_area_sq_km": (
                            population_exposure.flooded_area_sq_km
                        ),
                        "resolution_x": population_exposure.population_resolution_x,
                        "resolution_y": population_exposure.population_resolution_y,
                    }
                    if population_exposure is not None
                    else None
                ),
                "building_exposure": (
                    {
                        "source": building_exposure.source,
                        "building_dataset": building_exposure.building_dataset,
                        "flood_mask_dataset": building_exposure.flood_mask_dataset,
                        "buildings_at_risk": building_exposure.buildings_at_risk,
                        "total_buildings_in_analysis_area": (
                            building_exposure.total_buildings_in_analysis_area
                        ),
                        "affected_building_percentage": (
                            building_exposure.affected_building_percentage
                        ),
                    }
                    if building_exposure is not None
                    else None
                ),
                "railway_exposure": (
                    {
                        "source": railway_exposure.source,
                        "railway_dataset": railway_exposure.railway_dataset,
                        "flood_dataset": railway_exposure.flood_dataset,
                        "railways_at_risk": railway_exposure.railways_at_risk,
                        "total_railway_features_in_analysis_area": (
                            railway_exposure.total_railway_features_in_analysis_area
                        ),
                        "affected_railway_percentage": railway_exposure.affected_railway_percentage,
                        "affected_by_class": railway_exposure.affected_by_class,
                    }
                    if railway_exposure is not None
                    else None
                ),
            },
        )

        result = self.flood_engine.calculate(flood_inputs)

        exposure = self._exposure_assessment(
            population_exposure,
            building_exposure,
            railway_exposure,
        )

        return RiskAssessmentResponse(
            request_id=request_id,
            location=request.location,
            hazard=request.hazard,
            risk_assessment=RiskAssessment(
                risk_level=result.risk_level,
                risk_score=result.risk_score,
                affected_area_sq_km=result.affected_area_sq_km,
                methodology_version=result.methodology_version,
                contributing_factors=result.contributing_factors,
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
                    "rainfall": {
                        "total_rainfall_mm": rainfall.total_rainfall_mm,
                        "max_daily_rainfall_mm": rainfall.max_daily_rainfall_mm,
                        "rainfall_risk": rainfall.rainfall_risk,
                        "source": rainfall.source,
                        "total_dataset": rainfall.total_dataset,
                        "max_daily_dataset": rainfall.max_daily_dataset,
                        "period": rainfall.period,
                    },
                    "flood_extent": {
                        "flood_extent_value": flood_extent.flood_extent_value,
                        "flood_extent_risk": flood_extent.flood_extent_risk,
                        "flooded_area_sq_km": flood_extent.flooded_area_sq_km,
                        "source": flood_extent.source,
                        "dataset": flood_extent.dataset,
                    },
                    "river_proximity": {
                        "distance_to_river_m": river_proximity.distance_to_river_m,
                        "river_proximity_risk": river_proximity.river_proximity_risk,
                        "source": river_proximity.source,
                        "dataset": river_proximity.dataset,
                    },
                    "historical_flood": {
                        "flood_frequency": historical_flood.flood_frequency,
                        "flood_presence": historical_flood.flood_presence,
                        "maximum_flood_duration_days": historical_flood.maximum_flood_duration_days,
                        "maximum_flood_extent": historical_flood.maximum_flood_extent,
                        "frequency_risk": historical_flood.frequency_risk,
                        "presence_risk": historical_flood.presence_risk,
                        "duration_risk": historical_flood.duration_risk,
                        "extent_risk": historical_flood.extent_risk,
                        "historical_flood_risk": historical_flood.historical_flood_risk,
                        "source": historical_flood.source,
                        "frequency_dataset": historical_flood.frequency_dataset,
                        "presence_dataset": historical_flood.presence_dataset,
                        "duration_dataset": historical_flood.duration_dataset,
                        "extent_dataset": historical_flood.extent_dataset,
                    },
                    "population_exposure": (
                        {
                            "population_at_risk": (
                                population_exposure.population_at_risk
                            ),
                            "population_in_analysis_area": (
                                population_exposure.population_in_analysis_area
                            ),
                            "affected_population_percentage": (
                                population_exposure.affected_population_percentage
                            ),
                            "source": population_exposure.source,
                            "population_dataset": (
                                population_exposure.population_dataset
                            ),
                            "flood_mask_dataset": (
                                population_exposure.flood_mask_dataset
                            ),
                        }
                        if population_exposure is not None
                        else None
                    ),
                    "building_exposure": (
                        {
                            "buildings_at_risk": (
                                building_exposure.buildings_at_risk
                            ),
                            "total_buildings_in_analysis_area": (
                                building_exposure.total_buildings_in_analysis_area
                            ),
                            "affected_building_percentage": (
                                building_exposure.affected_building_percentage
                            ),
                            "source": building_exposure.source,
                            "building_dataset": (
                                building_exposure.building_dataset
                            ),
                            "flood_mask_dataset": (
                                building_exposure.flood_mask_dataset
                            ),
                        }
                        if building_exposure is not None
                        else None
                    ),
                    "railway_exposure": (
                        {
                            "railways_at_risk": railway_exposure.railways_at_risk,
                            "total_railway_features_in_analysis_area": (
                                railway_exposure.total_railway_features_in_analysis_area
                            ),
                            "affected_railway_percentage": railway_exposure.affected_railway_percentage,
                            "affected_by_class": railway_exposure.affected_by_class,
                            "source": railway_exposure.source,
                            "railway_dataset": railway_exposure.railway_dataset,
                            "flood_dataset": railway_exposure.flood_dataset,
                        }
                        if railway_exposure is not None
                        else None
                    ),
                },
            ),
            exposure=exposure,
            recommendations=(
                self._recommendations(result.risk_level)
                if request.include_recommendations
                else []
            ),
            map_data=spatial.map_data,
            explanation=(
                "Flood risk uses real SRTM elevation, NASA GPM IMERG rainfall, "
                "Sentinel-1 flood extent, local HydroSHEDS river proximity, "
                "historical flood indicators, and WorldPop population exposure. "
                "Population exposure is estimated by area-weighting the flood "
                "mask onto the WorldPop grid. The affected population percentage "
                "uses the valid population within the flood raster analysis "
                "bounding box as its denominator. Building exposure is calculated "
                "from the configured source (PostGIS by default) against the mapped "
                "flood extent; its denominator is buildings within the flood extent "
                "bounding box, not a user-selected radius."
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
                f"The {request.hazard.value} risk engine is not implemented yet."
            ),
        )

    @staticmethod
    def _exposure_assessment(
        population_exposure,
        building_exposure,
        railway_exposure=None,
    ) -> ExposureAssessment | None:
        if (
            population_exposure is None
            and building_exposure is None
            and railway_exposure is None
        ):
            return None

        details: dict[str, object] = {}
        if population_exposure is not None:
            details.update(
                {
                    "source": population_exposure.source,
                    "population_dataset": population_exposure.population_dataset,
                    "flood_mask_dataset": population_exposure.flood_mask_dataset,
                    "flooded_area_sq_km": population_exposure.flooded_area_sq_km,
                    "population_resolution_x": (
                        population_exposure.population_resolution_x
                    ),
                    "population_resolution_y": (
                        population_exposure.population_resolution_y
                    ),
                    "percentage_denominator": (
                        "population within the flood raster analysis bounding box"
                    ),
                }
            )
        if building_exposure is not None:
            details.update(
                {
                    "building_source": building_exposure.source,
                    "building_dataset": building_exposure.building_dataset,
                    "building_flood_mask_dataset": (
                        building_exposure.flood_mask_dataset
                    ),
                    "total_buildings_in_analysis_area": (
                        building_exposure.total_buildings_in_analysis_area
                    ),
                    "affected_building_percentage": (
                        building_exposure.affected_building_percentage
                    ),
                    "building_percentage_denominator": (
                        "buildings intersecting the mapped flood extent bounding box"
                    ),
                }
            )

        if railway_exposure is not None:
            details.update(
                {
                    "railway_source": railway_exposure.source,
                    "railway_dataset": railway_exposure.railway_dataset,
                    "railway_flood_dataset": railway_exposure.flood_dataset,
                    "railways_at_risk": railway_exposure.railways_at_risk,
                    "total_railway_features_in_analysis_area": (
                        railway_exposure.total_railway_features_in_analysis_area
                    ),
                    "affected_railway_percentage": (
                        railway_exposure.affected_railway_percentage
                    ),
                    "railways_at_risk_by_class": railway_exposure.affected_by_class,
                    "railway_percentage_denominator": (
                        "railway line features intersecting the mapped flood extent bounding box"
                    ),
                }
            )

        return ExposureAssessment(
            properties_at_risk=(
                building_exposure.buildings_at_risk
                if building_exposure is not None
                else None
            ),
            population_at_risk=(
                round(population_exposure.population_at_risk)
                if population_exposure is not None
                else None
            ),
            population_in_analysis_area=(
                population_exposure.population_in_analysis_area
                if population_exposure is not None
                else None
            ),
            affected_population_percentage=(
                population_exposure.affected_population_percentage
                if population_exposure is not None
                else None
            ),
            details=details,
        )

    @staticmethod
    def _recommendations(risk_level: str) -> list[Recommendation]:
        if risk_level == "very_high":
            return [
                Recommendation(
                    action="Move people and assets out of flooded or low-lying areas.",
                    priority="high",
                    rationale="Multiple flood indicators are at very high levels.",
                )
            ]
        if risk_level == "high":
            return [
                Recommendation(
                    action="Prepare evacuation routes and protect critical assets.",
                    priority="high",
                    rationale="Flood hazard indicators are high at this location.",
                )
            ]
        if risk_level == "moderate":
            return [
                Recommendation(
                    action="Monitor rainfall and river conditions and review local guidance.",
                    priority="medium",
                    rationale="Flood indicators are elevated but not at the highest band.",
                )
            ]
        return [
            Recommendation(
                action="Stay informed and maintain basic flood preparedness.",
                priority="low",
                rationale="Current flood indicators are in the low band.",
            )
        ]


@lru_cache(maxsize=1)
def get_risk_orchestrator() -> RiskOrchestrator:
    return RiskOrchestrator(get_settings())

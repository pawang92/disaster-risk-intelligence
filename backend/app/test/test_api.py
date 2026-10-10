from fastapi.testclient import TestClient

from app.main import app
from app.spatial.adapters.building import (
    BuildingExposureResult,
    BuildingPostGISExposureAdapter,
)
from app.spatial.adapters.critical_infrastructure import (
    CriticalInfrastructureExposureResult,
    CriticalInfrastructurePostGISExposureAdapter,
)
from app.services.risk_orchestrator import get_risk_orchestrator

client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"


def test_risk_assessment_requires_coordinates() -> None:
    response = client.post(
        "/api/v1/risk/assess",
        json={
            "location": {
                "village": "Test Village",
                "district": "Mumbai",
                "state": "Maharashtra",
            },
            "hazard": "flood",
            "question": "What is the flood risk?",
        },
    )

    assert response.status_code == 422


def test_risk_assessment_contract(monkeypatch) -> None:
    # Keep this API contract test independent of local PostgreSQL credentials.
    # Ignore optional road exposure configuration in a developer's .env.
    # Road exposure has separate adapter tests and is disabled for this API contract.
    monkeypatch.setattr(get_risk_orchestrator(), "road_exposure_adapter", None)
    monkeypatch.setattr(
        BuildingPostGISExposureAdapter,
        "calculate",
        lambda self: BuildingExposureResult(
            buildings_at_risk=1,
            total_buildings_in_analysis_area=100,
            affected_building_percentage=1.0,
            source="PostGIS building footprints + Sentinel-1 flood extent",
            building_dataset=self.building_table,
            flood_mask_dataset=self.flood_table,
        ),
    )

    monkeypatch.setattr(
        CriticalInfrastructurePostGISExposureAdapter,
        "calculate",
        lambda self: CriticalInfrastructureExposureResult(
            critical_assets_at_risk=3,
            total_critical_assets_in_analysis_area=30,
            affected_critical_asset_percentage=10.0,
            affected_by_category={"hospital": 2, "pharmacy": 1},
            totals_by_category={"hospital": 10, "pharmacy": 5, "school": 15},
            affected_percentage_by_category={
                "hospital": 20.0,
                "pharmacy": 20.0,
                "school": 0.0,
            },
            source="test POIs + flood extent",
            poi_dataset=self.poi_table,
            flood_dataset=self.flood_table,
        ),
    )

    response = client.post(
        "/api/v1/risk/assess",
        json={
            "location": {
                "village": "Test Village",
                "district": "Mumbai",
                "state": "Maharashtra",
                "latitude": 19.076,
                "longitude": 72.8777,
            },
            "hazard": "flood",
            "question": "What is the flood risk?",
        },
    )

    assert response.status_code == 200
    body = response.json()

    assert "request_id" in body
    assert body["hazard"] == "flood"

    risk_assessment = body["risk_assessment"]

    assert risk_assessment["risk_level"] in {
        "low",
        "moderate",
        "high",
        "very_high",
    }

    assert 0.0 <= risk_assessment["risk_score"] <= 1.0
    assert risk_assessment["methodology_version"] == "flood-v0.1"

    inputs = risk_assessment["inputs"]
    assert inputs["indicator_source"] == "real_spatial_data"

    elevation = inputs["elevation"]
    assert "elevation_m" in elevation
    assert "elevation_risk" in elevation
    assert isinstance(elevation["elevation_m"], (int, float))
    assert 0.0 <= elevation["elevation_risk"] <= 1.0

    rainfall = inputs["rainfall"]
    assert 0.0 <= rainfall["rainfall_risk"] <= 1.0

    flood_extent = inputs["flood_extent"]
    assert 0.0 <= flood_extent["flood_extent_risk"] <= 1.0
    assert flood_extent["flooded_area_sq_km"] is not None
    assert flood_extent["source"] == "Sentinel-1"

    river_proximity = inputs["river_proximity"]
    assert river_proximity["distance_to_river_m"] >= 0.0
    assert 0.0 <= river_proximity["river_proximity_risk"] <= 1.0
    assert river_proximity["source"] == "local_river_vector"

    historical_flood = inputs["historical_flood"]
    assert historical_flood["flood_frequency"] >= 0.0
    assert historical_flood["maximum_flood_duration_days"] >= 0.0
    assert 0.0 <= historical_flood["frequency_risk"] <= 1.0
    assert 0.0 <= historical_flood["presence_risk"] <= 1.0
    assert 0.0 <= historical_flood["duration_risk"] <= 1.0
    assert 0.0 <= historical_flood["extent_risk"] <= 1.0
    assert 0.0 <= historical_flood["historical_flood_risk"] <= 1.0
    assert historical_flood["source"] == "local_historical_flood_rasters"

    assert "building_exposure" in inputs
    critical = inputs["critical_infrastructure_exposure"]
    assert critical["critical_assets_at_risk"] == 3
    assert critical["affected_by_category"] == {"hospital": 2, "pharmacy": 1}
    assert body["exposure"]["critical_assets_at_risk"] == 3
    assert body["exposure"]["details"]["critical_assets_at_risk_by_category"] == {
        "hospital": 2,
        "pharmacy": 1,
    }
    assert body["exposure"]["roads_at_risk"] is None
    assert "historical_flood" in risk_assessment["contributing_factors"] or (
        historical_flood["historical_flood_risk"] < 0.50
    )
    assert body["recommendations"]
    assert body["map_data"]["features"]

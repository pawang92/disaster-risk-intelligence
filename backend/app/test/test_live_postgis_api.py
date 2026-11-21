"""Opt-in end-to-end test for the configured live PostGIS database.

Run from the repository root with:
    set RUN_LIVE_POSTGIS_TESTS=1
    D:\\python_projects\\geoai-copilot\\venv\\Scripts\\python.exe -m pytest backend\\app\\test\\test_live_postgis_api.py -v

This test intentionally uses the application's real settings and does not mock the
building exposure adapter. It is skipped during the normal unit-test suite.
"""
import os

import pytest
from fastapi.testclient import TestClient

from app.main import app


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_POSTGIS_TESTS") != "1",
    reason="Set RUN_LIVE_POSTGIS_TESTS=1 to run the live PostGIS API test.",
)


def test_risk_assessment_returns_live_postgis_building_exposure() -> None:
    client = TestClient(app)
    response = client.post(
        "/api/v1/risk/assess",
        json={
            "location": {
                "village": "Live PostGIS integration test",
                "district": "Mumbai",
                "state": "Maharashtra",
                "latitude": 19.076,
                "longitude": 72.8777,
            },
            "hazard": "flood",
            "include_exposure": True,
            "include_recommendations": True,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    inputs = body["risk_assessment"]["inputs"]
    building = inputs["building_exposure"]

    assert building is not None
    assert building["building_dataset"] == "mumbai_building_footprints"
    assert building["flood_mask_dataset"] == "mumbai_s1_flood_extent"

    affected = building["buildings_at_risk"]
    total = building["total_buildings_in_analysis_area"]
    percentage = building["affected_building_percentage"]

    assert isinstance(affected, int) and affected >= 0
    assert isinstance(total, int) and total >= affected
    assert isinstance(percentage, (int, float)) and 0 <= percentage <= 100

    exposure = body["exposure"]
    assert exposure is not None
    assert exposure["properties_at_risk"] == affected
    assert exposure["details"]["building_dataset"] == "mumbai_building_footprints"
    assert (
        exposure["details"]["building_flood_mask_dataset"]
        == "mumbai_s1_flood_extent"
    )

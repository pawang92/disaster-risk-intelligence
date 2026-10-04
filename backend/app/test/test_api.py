from fastapi.testclient import TestClient
from app.main import app
client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"


def test_risk_assessment_contract() -> None:
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

    # Basic response contract
    assert "request_id" in body
    assert body["hazard"] == "flood"

    # Risk assessment contract
    risk_assessment = body["risk_assessment"]

    assert risk_assessment["risk_level"] in {
        "low",
        "moderate",
        "high",
        "very_high",
    }

    assert 0.0 <= risk_assessment["risk_score"] <= 1.0
    assert risk_assessment["methodology_version"] == "flood-v0.1"
    # Real spatial-data integration
    inputs = risk_assessment["inputs"]
    assert inputs["indicator_source"] == "real_spatial_data"
    # Elevation adapter output
    assert "elevation" in inputs
    elevation = inputs["elevation"]
    assert "elevation_m" in elevation
    assert "elevation_risk" in elevation
    assert isinstance(
        elevation["elevation_m"],
        (int, float),
    )
    assert 0.0 <= elevation["elevation_risk"] <= 1.0

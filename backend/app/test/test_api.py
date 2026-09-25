from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_risk_assessment_contract() -> None:
    response = client.post(
        "/api/v1/risk/assess",
        json={
            "location": {"village": "Test Village", "district": "Mumbai"},
            "hazard": "flood",
            "question": "What is the flood risk?",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["hazard"] == "flood"
    assert body["risk_assessment"]["risk_level"] == "low"
    assert body["risk_assessment"]["risk_score"] == 0.0
    assert body["risk_assessment"]["methodology_version"] == "flood-v0.1"
    assert body["risk_assessment"]["inputs"]["indicator_source"] == "local_configuration"
    assert "request_id" in body

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
    assert body["risk_assessment"]["risk_level"] == "not_calculated"
    assert "request_id" in body

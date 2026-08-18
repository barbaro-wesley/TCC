from fastapi.testclient import TestClient

from services.api.main import app

client = TestClient(app)


def test_health_and_forecasts():
    assert client.get("/health").json()["status"] == "healthy"
    for horizon in (7, 14, 30):
        response = client.get("/forecast", params={"horizon": horizon})
        assert response.status_code == 200
        payload = response.json()
        assert payload["horizon_days"] == horizon
        assert payload["horizon_contract"]["calendar_days"] == {7: 7, 14: 14, 30: 28}[
            horizon
        ]
        assert payload["horizon_contract"]["legacy_id"] == (30 if horizon == 30 else None)


def test_dashboard_contract_and_decision_validation():
    dashboard = client.get("/api/dashboard")
    assert dashboard.status_code == 200
    payload = dashboard.json()
    assert payload["meta"]["geographyCode"] == "BR"
    assert len(payload["forecasts"]) == 3
    invalid = client.post(
        "/decision/simulate",
        json={"current_stock_liters": 200_000, "tank_capacity_liters": 100_000},
    )
    assert invalid.status_code == 422


def test_time_machine_enforces_availability():
    response = client.get("/time-machine", params={"as_of": "2025-01-01T00:00:00Z"})
    assert response.status_code == 200
    assert response.json()["known_observations"] > 0

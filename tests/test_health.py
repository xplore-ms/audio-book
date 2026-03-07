from unittest.mock import patch


def test_wake_up(client):
    response = client.get("/api/v1/health/wake")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "waking"
    assert "timestamp" in data


@patch("app.api.v1.health.client", return_value=True)
def test_readiness_check(mock_client, client):
    # Mocking client.admin.command('ping')
    mock_client.admin.command.return_value = {"ok": 1}

    response = client.get("/api/v1/health/ready")
    assert response.status_code == 200
    data = response.json()
    assert "ready" in data
    assert "mongo" in data
    assert "timestamp" in data

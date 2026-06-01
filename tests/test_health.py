"""Teste do endpoint /health usado pelo uptime monitoring."""


def test_health_endpoint_returns_ok(client):
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["service"] == "coach-pam-api"
    assert data["db"] == "ok"


def test_health_endpoint_does_not_require_auth(client):
    """Health checks precisam funcionar sem token (UptimeRobot etc)."""
    # client é o cliente sem header de auth
    res = client.get("/health")
    assert res.status_code == 200

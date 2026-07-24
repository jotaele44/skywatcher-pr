from fastapi.testclient import TestClient

from server.backend.main import app


def test_generic_entity_api_is_preserved():
    client = TestClient(app)
    response = client.get("/api/entities/PRAirports")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_health_is_preserved_and_console_is_additive():
    client = TestClient(app)
    assert client.get("/api/health").status_code == 200
    console = client.get("/api/console/capabilities")
    assert console.status_code == 200
    assert console.json()["capability_count"] == 24

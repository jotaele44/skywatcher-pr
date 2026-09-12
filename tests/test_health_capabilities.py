def test_health_fails_closed_when_core_analysis_is_unavailable(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    import server.backend.main as backend

    monkeypatch.setattr(backend, "_lens_registries", lambda: None)
    payload = TestClient(backend.app).get("/health").json()

    assert payload["status"] == "degraded"
    assert payload["components"]["analysis_registry"] is False

from fastapi.testclient import TestClient
from desktop.app_server import CONTENT_SECURITY_POLICY, app


def test_desktop_spa_emits_phase3_security_headers():
    response = TestClient(app).get('/console', headers={'accept': 'text/html'})
    assert response.status_code in {200, 503}
    assert response.headers['content-security-policy'] == CONTENT_SECURITY_POLICY
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert response.headers['permissions-policy'].startswith('geolocation=(self)')
    assert "worker-src 'self' blob:" in CONTENT_SECURITY_POLICY
    assert "connect-src 'self' blob:" in CONTENT_SECURITY_POLICY

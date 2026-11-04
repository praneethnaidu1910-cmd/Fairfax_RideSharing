"""TASKS.md #18: a hosting platform needs a route to poll that actually
proves the app can reach its database, not just that the process is up."""

from fastapi.testclient import TestClient

from app.main import app


def test_healthz_ok_when_database_reachable():
    with TestClient(app) as client:
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


def test_healthz_503_when_database_unreachable():
    with TestClient(app) as client:

        def _broken_session_factory():
            raise RuntimeError("no connection")

        app.state.session_factory = _broken_session_factory
        response = client.get("/healthz")
        assert response.status_code == 503
        assert response.json()["status"] == "error"

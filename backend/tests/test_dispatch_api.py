from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_match_returns_nearest_available_driver():
    # Close to Deepa (d4, available) in Reston, away from busy Quentin (d17).
    response = client.post("/match", json={"rider_location": {"lat": 38.96, "lng": -77.355}})

    assert response.status_code == 200
    body = response.json()
    assert body["driver_id"] == "d4"
    assert body["distance_miles"] >= 0


def test_match_rejects_malformed_request():
    response = client.post("/match", json={"rider_location": {"lat": "not-a-number", "lng": -77.355}})

    assert response.status_code == 422


def test_match_rejects_physically_impossible_coordinates():
    # Reproduction of the same bug tests/test_schemas.py's
    # test_location_rejects_out_of_range_coordinates covers for the
    # pooling engine's own Location: before the dispatch module's
    # Location got the same lat/lng bounds, this returned 200 with a
    # "nearest" driver computed from a nonsense distance instead of 422.
    response = client.post("/match", json={"rider_location": {"lat": 999.0, "lng": -500.0}})

    assert response.status_code == 422


def test_match_returns_404_when_no_drivers_available(monkeypatch):
    from app.dispatch.schemas import Driver, Location

    all_busy = [Driver(id="d1", name="One", location=Location(lat=38.9, lng=-77.3), status="busy")]
    monkeypatch.setattr("app.dispatch.router.SAMPLE_DRIVERS", all_busy)

    response = client.post("/match", json={"rider_location": {"lat": 38.9, "lng": -77.3}})

    assert response.status_code == 404

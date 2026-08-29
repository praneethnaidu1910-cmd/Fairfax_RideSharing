"""TASKS.md #11: minimal frontend, verified against the page routes
themselves (not just the JSON API underneath them)."""

from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app.main import app

FAIRFAX = (38.8462, -77.3064)
ALDIE = (38.9757, -77.6122)


def _one_off_form(rider_id, contact="555-0100-secret"):
    earliest = datetime.utcnow() + timedelta(hours=2)
    latest = earliest + timedelta(minutes=30)
    return {
        "rider_id": rider_id,
        "origin_place": "Fairfax",
        "origin_lat": str(FAIRFAX[0]),
        "origin_lng": str(FAIRFAX[1]),
        "destination_place": "Aldie",
        "destination_lat": str(ALDIE[0]),
        "destination_lng": str(ALDIE[1]),
        "schedule_type": "one_off",
        "earliest_departure": earliest.isoformat(timespec="minutes"),
        "latest_departure": latest.isoformat(timespec="minutes"),
        "seats_needed": "1",
        "contact": contact,
    }


def test_new_page_renders_a_form():
    with TestClient(app) as client:
        response = client.get("/new")

    assert response.status_code == 200
    assert "<form" in response.text
    assert 'name="origin_place"' in response.text


def test_browse_page_lists_no_requests_initially():
    with TestClient(app) as client:
        response = client.get("/browse")

    assert response.status_code == 200
    assert "No open requests yet" in response.text


def test_submitting_form_creates_request_visible_on_browse_page():
    form_data = _one_off_form("web-form-rider")

    with TestClient(app) as client:
        post_response = client.post("/new", data=form_data, follow_redirects=False)
        assert post_response.status_code == 303
        assert post_response.headers["location"] == "/browse"

        browse_response = client.get("/browse")

    assert browse_response.status_code == 200
    assert "web-form-rider" in browse_response.text
    # Privacy: the browse page is the same coarse view GET /requests
    # returns -- never the precise coordinates or contact submitted above.
    assert "555-0100-secret" not in browse_response.text
    assert str(FAIRFAX[0]) not in browse_response.text
    assert str(FAIRFAX[1]) not in browse_response.text


def test_submitting_recurring_schedule_creates_request_visible_on_browse_page():
    form_data = {
        "rider_id": "recurring-rider",
        "origin_place": "Fairfax",
        "origin_lat": str(FAIRFAX[0]),
        "origin_lng": str(FAIRFAX[1]),
        "destination_place": "Aldie",
        "destination_lat": str(ALDIE[0]),
        "destination_lng": str(ALDIE[1]),
        "schedule_type": "recurring",
        "weekdays": ["0", "2", "4"],
        "earliest_departure_time": "09:00",
        "latest_departure_time": "09:30",
        "seats_needed": "1",
        "contact": "555-0200",
    }

    with TestClient(app) as client:
        post_response = client.post("/new", data=form_data, follow_redirects=False)
        assert post_response.status_code == 303

        browse_response = client.get("/browse")

    assert browse_response.status_code == 200
    assert "recurring-rider" in browse_response.text


def test_missing_geocoded_coordinates_reprompts_form_without_creating_request():
    form_data = _one_off_form("no-geocode-rider")
    form_data["origin_lat"] = ""
    form_data["origin_lng"] = ""

    with TestClient(app) as client:
        response = client.post("/new", data=form_data, follow_redirects=False)
        assert response.status_code == 400
        assert "Could not resolve pickup place" in response.text

        browse_response = client.get("/browse")

    assert "no-geocode-rider" not in browse_response.text

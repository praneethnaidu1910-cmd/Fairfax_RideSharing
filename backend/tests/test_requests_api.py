from datetime import datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app

# Real Fairfax/Aldie coordinates, mirroring app/sample_data.py's rider-1 and
# rider-7 (close origin, same destination, overlapping window) -- the
# known-good same-direction pair used elsewhere to exercise a real match.
FAIRFAX = (38.8462, -77.3064)
NEAR_FAIRFAX = (38.8500, -77.3100)
ALDIE = (38.9757, -77.6122)


def _one_off_payload(rider_id, origin, destination, minutes_from_now, duration_minutes, contact):
    earliest = datetime.utcnow() + timedelta(minutes=minutes_from_now)
    latest = earliest + timedelta(minutes=duration_minutes)
    return {
        "rider_id": rider_id,
        "origin": {"lat": origin[0], "lng": origin[1]},
        "destination": {"lat": destination[0], "lng": destination[1]},
        "schedule": {
            "earliest_departure": earliest.isoformat(),
            "latest_departure": latest.isoformat(),
        },
        "seats_needed": 1,
        "contact": contact,
    }


def test_create_request_response_is_coarse_and_never_leaks_precise_or_contact():
    payload = _one_off_payload(
        "rider-privacy-test", FAIRFAX, ALDIE, 120, 30, contact="555-9999-secret"
    )

    with TestClient(app) as client:
        response = client.post("/requests", json=payload)

    assert response.status_code == 201
    body = response.json()
    assert "contact" not in body
    assert "origin" not in body
    assert "destination" not in body
    assert body["origin_area"] and body["destination_area"]
    assert body["status"] == "open"
    assert "555-9999-secret" not in response.text
    assert str(FAIRFAX[0]) not in response.text
    assert str(FAIRFAX[1]) not in response.text


def test_list_requests_never_includes_precise_location_or_contact():
    payload = _one_off_payload(
        "rider-privacy-test-2", FAIRFAX, ALDIE, 120, 30, contact="555-8888-secret"
    )

    with TestClient(app) as client:
        created = client.post("/requests", json=payload).json()
        response = client.get("/requests")

    assert response.status_code == 200
    assert "555-8888-secret" not in response.text
    assert str(FAIRFAX[0]) not in response.text
    assert str(FAIRFAX[1]) not in response.text

    listed = {entry["id"]: entry for entry in response.json()}
    assert created["id"] in listed
    entry = listed[created["id"]]
    assert "contact" not in entry
    assert "origin" not in entry
    assert "destination" not in entry
    assert entry["origin_area"] == created["origin_area"]


def test_list_requests_fuzzes_the_departure_window_wider_than_posted():
    earliest = datetime.utcnow() + timedelta(hours=2)
    latest = earliest + timedelta(minutes=20)
    payload = {
        "rider_id": "rider-fuzz-test",
        "origin": {"lat": FAIRFAX[0], "lng": FAIRFAX[1]},
        "destination": {"lat": ALDIE[0], "lng": ALDIE[1]},
        "schedule": {
            "earliest_departure": earliest.isoformat(),
            "latest_departure": latest.isoformat(),
        },
        "seats_needed": 1,
        "contact": "555-7777",
    }

    with TestClient(app) as client:
        created = client.post("/requests", json=payload).json()

    fuzzed_earliest = datetime.fromisoformat(created["schedule"]["earliest_departure"])
    fuzzed_latest = datetime.fromisoformat(created["schedule"]["latest_departure"])
    assert fuzzed_earliest < earliest
    assert fuzzed_latest > latest


def test_websocket_streams_a_match_between_two_compatible_requests():
    first_payload = _one_off_payload("rider-ws-a", FAIRFAX, ALDIE, 120, 30, contact="555-0201")
    second_payload = _one_off_payload(
        "rider-ws-b", NEAR_FAIRFAX, ALDIE, 125, 30, contact="555-0202"
    )

    with TestClient(app) as client:
        with client.websocket_connect("/matches") as websocket:
            first = client.post("/requests", json=first_payload)
            second = client.post("/requests", json=second_payload)

            assert first.status_code == 201
            assert second.status_code == 201

            match_event = websocket.receive_json()

    assert set(match_event["request_ids"]) == {first.json()["id"], second.json()["id"]}


def test_matched_counterpart_gets_full_view_everyone_else_gets_redacted():
    payload_a = _one_off_payload("rider-reveal-a", FAIRFAX, ALDIE, 120, 30, contact="555-0301")
    payload_b = _one_off_payload(
        "rider-reveal-b", NEAR_FAIRFAX, ALDIE, 125, 30, contact="555-0302"
    )

    with TestClient(app) as client:
        with client.websocket_connect("/matches") as websocket:
            a = client.post("/requests", json=payload_a).json()
            b = client.post("/requests", json=payload_b).json()
            websocket.receive_json()  # block until the two are actually matched

        full_view = client.get(f"/requests/{a['id']}", params={"viewer_request_id": b["id"]})
        redacted_view = client.get(f"/requests/{a['id']}")
        wrong_viewer_view = client.get(
            f"/requests/{a['id']}", params={"viewer_request_id": a["id"]}
        )

    assert full_view.status_code == 200
    full_body = full_view.json()
    assert full_body["contact"] == "555-0301"
    assert full_body["origin"] == {"lat": FAIRFAX[0], "lng": FAIRFAX[1]}

    for redacted in (redacted_view, wrong_viewer_view):
        assert redacted.status_code == 200
        body = redacted.json()
        assert "contact" not in body
        assert "origin" not in body
        assert "destination" not in body
        assert body["origin_area"]


def test_get_unmatched_requests_own_id_is_still_redacted():
    payload = _one_off_payload("rider-reveal-solo", FAIRFAX, ALDIE, 1, 5, contact="555-0303")

    with TestClient(app) as client:
        created = client.post("/requests", json=payload).json()
        response = client.get(f"/requests/{created['id']}")

    assert response.status_code == 200
    body = response.json()
    assert "contact" not in body
    assert "origin" not in body


def test_get_unknown_request_id_returns_404():
    with TestClient(app) as client:
        response = client.get(f"/requests/{uuid4()}")

    assert response.status_code == 404


def test_open_request_past_its_window_reports_expired_status():
    # TASKS.md #14: nothing ever flips this request's persisted status --
    # both read paths compute "expired" live from the (already-past)
    # window instead.
    payload = _one_off_payload(
        "rider-expired-test", FAIRFAX, ALDIE, -120, 30, contact="555-0404"
    )

    with TestClient(app) as client:
        created = client.post("/requests", json=payload).json()
        detail = client.get(f"/requests/{created['id']}")
        listing = client.get("/requests")

    assert created["status"] == "expired"
    assert detail.json()["status"] == "expired"
    entry = {r["id"]: r for r in listing.json()}[created["id"]]
    assert entry["status"] == "expired"

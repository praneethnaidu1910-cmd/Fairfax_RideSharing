"""TASKS.md #12: live match updates + reveal on the "my request" page.

Server-side pieces this can actually exercise through TestClient: the
/matches broadcast reaching two simultaneous connections (the two-browser-
tabs case the manual smoke test covers), and /mine/{id} rendering the
reveal once a request is matched. The client-side WebSocket wiring itself
(static/live.js) is what the manual smoke test in the README verifies.
"""

from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app.main import app

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


def test_two_simultaneous_websocket_connections_both_see_the_same_match():
    # The two-browser-tabs case itself: before engine.subscribe() existed,
    # only one of two simultaneous /matches connections would ever get a
    # given match (they shared one queue, competing-consumer style).
    payload_a = _one_off_payload("rider-live-a", FAIRFAX, ALDIE, 120, 30, contact="555-0401")
    payload_b = _one_off_payload(
        "rider-live-b", NEAR_FAIRFAX, ALDIE, 125, 30, contact="555-0402"
    )

    with TestClient(app) as client:
        with client.websocket_connect("/matches") as tab_a, client.websocket_connect(
            "/matches"
        ) as tab_b:
            a = client.post("/requests", json=payload_a).json()
            b = client.post("/requests", json=payload_b).json()

            match_seen_by_a = tab_a.receive_json()
            match_seen_by_b = tab_b.receive_json()

    assert set(match_seen_by_a["request_ids"]) == {a["id"], b["id"]}
    assert set(match_seen_by_b["request_ids"]) == {a["id"], b["id"]}


def test_mine_page_shows_waiting_before_match_and_reveal_after():
    payload_a = _one_off_payload("rider-mine-a", FAIRFAX, ALDIE, 120, 30, contact="555-0501")
    payload_b = _one_off_payload(
        "rider-mine-b", NEAR_FAIRFAX, ALDIE, 125, 30, contact="555-0502"
    )

    with TestClient(app) as client:
        a = client.post("/requests", json=payload_a).json()

        waiting_page = client.get(f"/mine/{a['id']}")
        assert waiting_page.status_code == 200
        assert "Waiting for a match" in waiting_page.text
        assert "555-0501" not in waiting_page.text

        with client.websocket_connect("/matches") as websocket:
            b = client.post("/requests", json=payload_b).json()
            websocket.receive_json()  # block until actually matched

        matched_page = client.get(f"/mine/{a['id']}")

    assert matched_page.status_code == 200
    assert "Matched!" in matched_page.text
    assert "rider-mine-b" in matched_page.text
    assert "555-0502" in matched_page.text  # the counterpart's contact, revealed
    assert "555-0501" not in matched_page.text  # never your own contact echoed back


def test_mine_page_unknown_request_id_404s():
    with TestClient(app) as client:
        response = client.get("/mine/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404

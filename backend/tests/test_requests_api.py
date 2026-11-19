import threading
from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from app import router as router_module
from app.db import make_session_factory
from app.main import app
from app.matching.engine import MatchingEngine
from app.router import cancel_request
from app.schemas import Location, OneOffSchedule, RequestStatus, RideRequest
from app.store import RequestStore

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


def test_create_request_rejects_impossible_coordinates():
    # app/schemas.py's Location now range-checks lat/lng -- before this, a
    # client typo like lat=999 was accepted (201) and fed straight into the
    # matching engine's distance/bearing math, which doesn't error on an
    # impossible point, it just silently computes nonsense.
    payload = _one_off_payload(
        "rider-bad-coords", (999.0, -500.0), ALDIE, 120, 30, contact="555-0000"
    )

    with TestClient(app) as client:
        response = client.post("/requests", json=payload)

    assert response.status_code == 422


def test_create_request_rejects_timezone_aware_departure_times():
    # app/schemas.py's OneOffSchedule now rejects a tz-aware
    # earliest_departure/latest_departure -- before this, a perfectly
    # normal thing for a non-browser API client to send (an ISO 8601
    # string with a "-05:00" offset or a "Z" suffix, unlike the naive
    # strings every other test here posts) 500'd instead of 422ing: the
    # comparison in OneOffSchedule's own "latest must not be before
    # earliest" check raised a bare TypeError ("can't compare
    # offset-naive and offset-aware datetimes"), since every other
    # datetime in this codebase (scoring.is_expired()'s
    # datetime.utcnow(), the DateTime(timezone=False) columns requests
    # get persisted to) is naive.
    earliest = datetime.utcnow() + timedelta(hours=2)
    latest = earliest + timedelta(minutes=30)
    payload = {
        "rider_id": "rider-tz-aware",
        "origin": {"lat": FAIRFAX[0], "lng": FAIRFAX[1]},
        "destination": {"lat": ALDIE[0], "lng": ALDIE[1]},
        "schedule": {
            "earliest_departure": earliest.isoformat() + "-05:00",
            "latest_departure": latest.isoformat() + "-05:00",
        },
        "seats_needed": 1,
        "contact": "555-0601",
    }

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/requests", json=payload)

    assert response.status_code == 422


def test_create_request_rejects_a_schedule_mixing_one_off_and_recurring_fields():
    # app/schemas.py's OneOffSchedule/RecurringSchedule now both set
    # extra="forbid". Before this, `schedule` carrying fields from *both*
    # shapes at once -- plausible from a non-browser client with leftover
    # fields from editing one schedule type into another -- didn't 422 at
    # all: Pydantic's smart-union matching on `Union[OneOffSchedule,
    # RecurringSchedule]` silently picked RecurringSchedule (the second
    # member) and just dropped earliest_departure/latest_departure, so this
    # returned 201 as a weekly Mon/Tue/Wed recurring request instead of the
    # one-off trip the earliest_departure/latest_departure fields actually
    # named -- no error, no sign the stored request didn't mean what was
    # posted.
    earliest = datetime.utcnow() + timedelta(hours=2)
    latest = earliest + timedelta(minutes=30)
    payload = {
        "rider_id": "rider-mixed-schedule",
        "origin": {"lat": FAIRFAX[0], "lng": FAIRFAX[1]},
        "destination": {"lat": ALDIE[0], "lng": ALDIE[1]},
        "schedule": {
            "earliest_departure": earliest.isoformat(),
            "latest_departure": latest.isoformat(),
            "weekdays": [0, 1, 2],
            "earliest_departure_time": "09:00:00",
            "latest_departure_time": "09:30:00",
        },
        "seats_needed": 1,
        "contact": "555-0602",
    }

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/requests", json=payload)

    assert response.status_code == 422


def test_create_request_rejects_empty_contact():
    # app/schemas.py's RideRequestCreate now requires a non-empty contact
    # -- before this, an empty string was accepted (201), stored, and
    # would reach a real match untouched: the matched counterpart's
    # reveal would show an empty Contact line, with no way to actually
    # reach the other rider, silently defeating SCOPE.md's whole stated
    # reason for collecting this field in the first place.
    payload = _one_off_payload("rider-no-contact", FAIRFAX, ALDIE, 120, 30, contact="")

    with TestClient(app) as client:
        response = client.post("/requests", json=payload)

    assert response.status_code == 422


def test_create_request_rejects_empty_rider_id():
    payload = _one_off_payload("", FAIRFAX, ALDIE, 120, 30, contact="555-0000")

    with TestClient(app) as client:
        response = client.post("/requests", json=payload)

    assert response.status_code == 422


def test_create_request_rejects_whitespace_only_rider_id_or_contact():
    # Field(min_length=1) alone didn't catch this -- a whitespace-only
    # string still has length >= 1. Confirmed this was real before the
    # fix: this exact payload returned 201, stored a rider_id/contact that
    # look blank to anyone who ever sees them (the matched counterpart's
    # reveal included), the same gap the empty-string fix above was
    # supposed to close.
    payload = _one_off_payload("   ", FAIRFAX, ALDIE, 120, 30, contact="   ")

    with TestClient(app) as client:
        response = client.post("/requests", json=payload)

    assert response.status_code == 422


def test_create_request_rejects_a_nul_character_in_rider_id_or_contact():
    # A NUL byte ("\u0000") is a perfectly ordinary JSON string character
    # -- neither empty nor whitespace, so neither fix above catches it --
    # but rider_id/contact end up in a Postgres text column
    # (app/store.py's RequestStore.add()), and libpq refuses outright to
    # send a string containing one. Confirmed this was real, not
    # theoretical, with a live TestClient call before this fix: this exact
    # payload 500'd inside RequestStore.add()'s session.commit() with
    # `ValueError: A string literal cannot contain NUL (0x00) characters`,
    # not a 422 from intake -- the request never got validated away, it
    # crashed the store instead.
    payload = _one_off_payload("rider-\x00null", FAIRFAX, ALDIE, 120, 30, contact="555-0000")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/requests", json=payload)

    assert response.status_code == 422


def test_create_request_rejects_seats_needed_beyond_postgres_integer_range():
    # app/models.py's seats_needed column is a plain Postgres INTEGER (4
    # bytes) -- Field(ge=1) on RideRequestCreate/RideRequest put a floor
    # on this field but never a ceiling, so a value past the column's
    # signed range used to validate cleanly through intake and crash deep
    # inside the DB driver instead. Confirmed this was real, not
    # theoretical, with a live TestClient call before this fix: this
    # exact payload 500'd inside RequestStore.add()'s session.commit()
    # with `psycopg2.errors.NumericValueOutOfRange: integer out of
    # range`, not a 422 from intake.
    payload = _one_off_payload("rider-huge-party", FAIRFAX, ALDIE, 120, 30, contact="555-0603")
    payload["seats_needed"] = 99_999_999_999_999

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/requests", json=payload)

    assert response.status_code == 422


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

    listed = {entry["rider_id"]: entry for entry in response.json()}
    assert created["rider_id"] in listed
    entry = listed[created["rider_id"]]
    assert "contact" not in entry
    assert "origin" not in entry
    assert "destination" not in entry
    assert entry["origin_area"] == created["origin_area"]


def test_list_requests_never_includes_the_request_id_either():
    # Not just contact/precise-location: `id` itself has to stay out of
    # this list too. GET /requests/{id}?viewer_request_id= (TASKS.md #7)
    # treats knowing a request's own id as the *only* proof needed to see
    # its precise origin/destination/contact once matched -- that id is
    # supposed to be a secret only the request's own poster has (handed
    # back once, by POST /requests' own response) and that a matched
    # counterpart only ever learns from the /matches WebSocket event
    # naming them. An uninvolved caller with no relationship to a request
    # at all could previously read its id straight off this open list
    # before any match happened, then use that -- plus a second scraped id
    # that vanished from this same list around the same time -- as a
    # completely unguessed "viewer_request_id" once they matched each
    # other. Confirmed real before this fix with a live script: two
    # compatible riders' ids, read straight off a real GET /requests call
    # made before they matched, were enough on their own (no other
    # knowledge, no websocket) to pull a full reveal through GET
    # /requests/{a}?viewer_request_id={b} once both vanished from this
    # list. Regression coverage for the actual end-to-end scrape-then-
    # reveal scenario lives in test_scraping_the_open_list_can_no_longer_
    # reveal_a_matched_pair below; this test is the narrower "the field
    # simply isn't there" check.
    payload = _one_off_payload(
        "rider-id-not-in-listing", FAIRFAX, ALDIE, 150, 30, contact="555-8887"
    )

    with TestClient(app) as client:
        client.post("/requests", json=payload)
        response = client.get("/requests")

    assert response.status_code == 200
    for entry in response.json():
        assert "id" not in entry


def test_scraping_the_open_list_before_a_match_can_no_longer_reveal_it_after():
    # The real end-to-end attack GET /requests used to allow: an otherwise
    # completely uninvolved caller scrapes every id off the public open
    # list *before* any match happens (nothing here requires auth or
    # guessing -- SCOPE.md is open-join, no SMS/OTP), notices two
    # previously-listed ids vanish from the list together (a match), and
    # uses that publicly-scraped pair as viewer_request_id against each
    # other to pull a full reveal -- no websocket, no secret the attacker
    # wasn't already handed for free. This has to fail now that `id` is
    # gone from the open list's own response -- an attacker scraping this
    # list has nothing at all to pair up, before or after a match happens.
    payload_a = _one_off_payload(
        "rider-scrape-a", FAIRFAX, ALDIE, 120, 30, contact="555-0601-secret"
    )

    with TestClient(app) as client:
        a = client.post("/requests", json=payload_a).json()

        # The attacker's own view of the world, scraped *before* any match
        # -- the real window this bug was exploitable in. Real a["id"]
        # above came from a's own POST response (a's own legitimate
        # hand-off), not from anything an uninvolved scraper could read.
        scraped_while_open = client.get("/requests").json()
        scraped_ids = {entry.get("id") for entry in scraped_while_open}

        payload_b = _one_off_payload(
            "rider-scrape-b", NEAR_FAIRFAX, ALDIE, 125, 30, contact="555-0602-secret"
        )
        with client.websocket_connect("/matches") as websocket:
            websocket.send_json({"request_id": a["id"]})
            b = client.post("/requests", json=payload_b).json()
            websocket.receive_json()  # block until the two are actually matched

    assert scraped_ids == {None}
    assert a["id"] not in scraped_ids
    assert b["id"] not in scraped_ids


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
            assert first.status_code == 201
            # Register this connection against the first request's own id
            # right away -- before posting the second request, which is
            # what can actually produce the match (app/router.py's
            # stream_matches() subscribes before waiting for this message,
            # so nothing in between is lost either way).
            websocket.send_json({"request_id": first.json()["id"]})

            second = client.post("/requests", json=second_payload)
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
            websocket.send_json({"request_id": a["id"]})
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


def test_cancel_open_request_sets_cancelled_status_and_drops_it_from_the_open_list():
    # A lone request (no compatible pair in this payload) so it stays OPEN
    # and pooled, not MATCHED, until cancelled.
    payload = _one_off_payload(
        "rider-cancel-test", (38.9, -77.6), (38.7, -77.0), 180, 30, contact="555-0501"
    )

    with TestClient(app) as client:
        created = client.post("/requests", json=payload).json()
        cancel_response = client.post(f"/requests/{created['id']}/cancel")
        detail = client.get(f"/requests/{created['id']}")
        listing = client.get("/requests")

    assert cancel_response.status_code == 200
    cancel_body = cancel_response.json()
    assert cancel_body["status"] == "cancelled"
    assert "contact" not in cancel_body
    assert detail.json()["status"] == "cancelled"
    assert created["rider_id"] not in {r["rider_id"] for r in listing.json()}


def test_cancel_unknown_request_id_returns_404():
    with TestClient(app) as client:
        response = client.post(f"/requests/{uuid4()}/cancel")

    assert response.status_code == 404


def test_cancel_already_cancelled_request_returns_409():
    payload = _one_off_payload(
        "rider-double-cancel", (38.9, -77.6), (38.7, -77.0), 180, 30, contact="555-0502"
    )

    with TestClient(app) as client:
        created = client.post("/requests", json=payload).json()
        first_cancel = client.post(f"/requests/{created['id']}/cancel")
        second_cancel = client.post(f"/requests/{created['id']}/cancel")

    assert first_cancel.status_code == 200
    assert second_cancel.status_code == 409


def test_cancel_a_matched_request_returns_409():
    payload_a = _one_off_payload("rider-cancel-matched-a", FAIRFAX, ALDIE, 120, 30, contact="555-0503")
    payload_b = _one_off_payload(
        "rider-cancel-matched-b", NEAR_FAIRFAX, ALDIE, 125, 30, contact="555-0504"
    )

    with TestClient(app) as client:
        with client.websocket_connect("/matches") as websocket:
            a = client.post("/requests", json=payload_a).json()
            websocket.send_json({"request_id": a["id"]})
            client.post("/requests", json=payload_b)
            websocket.receive_json()  # block until the two are actually matched

        response = client.post(f"/requests/{a['id']}/cancel")

    assert response.status_code == 409


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
    entry = {r["rider_id"]: r for r in listing.json()}[created["rider_id"]]
    assert entry["status"] == "expired"


def test_cancel_an_expired_request_returns_409():
    # cancel_request()'s own docstring (TASKS.md #15) always said EXPIRED
    # should 409 like MATCHED/CANCELLED do -- but it compared against the
    # raw *stored* status, and TASKS.md #14's whole point is that an
    # expired one-off request's stored status stays "open" forever (only
    # to_public() computes "expired" at read time). So this 409 never
    # actually fired, and a caller got a 200 "cancelling" a request that
    # was already unmatchable -- which also reset status_changed_at to
    # now, pushing out app/retention.py's 30-day anonymization clock
    # instead of leaving it counting from the window's own
    # latest_departure.
    payload = _one_off_payload(
        "rider-cancel-expired", FAIRFAX, ALDIE, -120, 30, contact="555-0505"
    )

    with TestClient(app) as client:
        created = client.post("/requests", json=payload).json()
        assert created["status"] == "expired"
        response = client.post(f"/requests/{created['id']}/cancel")
        detail = client.get(f"/requests/{created['id']}")

    assert response.status_code == 409
    assert response.json()["detail"] == "cannot cancel a request with status 'expired'"
    # Still just "expired", not silently flipped to "cancelled".
    assert detail.json()["status"] == "expired"


def _store_backed_request(rider_id: str, lat: float, lng: float) -> RideRequest:
    now = datetime.utcnow()
    return RideRequest(
        rider_id=rider_id,
        origin=Location(lat=lat, lng=lng),
        destination=Location(lat=38.9757, lng=-77.6122),
        schedule=OneOffSchedule(
            earliest_departure=now + timedelta(hours=2),
            latest_departure=now + timedelta(hours=2, minutes=30),
        ),
        seats_needed=1,
        contact="555-0506",
    )


def test_cancel_does_not_revert_a_match_that_landed_between_its_read_and_its_write(monkeypatch):
    # cancel_request() (app/router.py) is a sync route, which Starlette
    # dispatches to a threadpool worker, not the asyncio event loop
    # run_forever()/on_new_request() run on -- so a real match for this
    # exact request can land in the gap between cancel_request()'s first
    # read of it and the write that flips it to CANCELLED. Forces that
    # exact interleaving deterministically: pauses cancel_request() right
    # after its first read (via a monkeypatched to_public, called with the
    # OPEN request it just read), runs the real on_new_request() against
    # that same request from the "concurrent" side while paused, then lets
    # cancel_request() resume into its own second read/recheck.
    session_factory = make_session_factory()
    store = RequestStore(session_factory)
    engine = MatchingEngine(store=store)
    fake_request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(store=store, engine=engine)))

    target = _store_backed_request("rider-cancel-race-target", 38.8462, -77.3064)
    incoming = _store_backed_request("rider-cancel-race-incoming", 38.8500, -77.3100)
    store.add(target)
    store.add(incoming)
    engine._unmatched.append(target)

    reached = threading.Event()
    release = threading.Event()
    real_to_public = router_module.to_public
    call_count = {"n": 0}

    def pausing_to_public(request_obj):
        call_count["n"] += 1
        if call_count["n"] == 1:
            reached.set()
            release.wait(timeout=5)
        return real_to_public(request_obj)

    monkeypatch.setattr(router_module, "to_public", pausing_to_public)

    result: dict = {}

    def run_cancel():
        try:
            result["response"] = cancel_request(target.id, fake_request)
        except Exception as exc:
            result["exception"] = exc

    worker = threading.Thread(target=run_cancel)
    worker.start()
    assert reached.wait(timeout=5), "cancel_request never reached its first read"

    matches = engine.on_new_request(incoming)
    assert len(matches) == 1

    release.set()
    worker.join(timeout=5)

    assert "response" not in result, f"cancel_request did not 409: {result}"
    exc = result["exception"]
    assert getattr(exc, "status_code", None) == 409

    stored_target = store.get(target.id)
    assert stored_target.status == RequestStatus.MATCHED
    assert stored_target.matched_with == incoming.id
    stored_incoming = store.get(incoming.id)
    assert stored_incoming.status == RequestStatus.MATCHED
    assert stored_incoming.matched_with == target.id

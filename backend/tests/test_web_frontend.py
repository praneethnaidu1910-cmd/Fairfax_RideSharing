"""TASKS.md #11: minimal frontend, verified against the page routes
themselves (not just the JSON API underneath them)."""

import re
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
        # Redirects to the rider's own "waiting for a match" page (#12),
        # not straight to /browse -- that page is where request_id lives.
        location = post_response.headers["location"]
        assert location.startswith("/mine/")

        mine_response = client.get(location)
        browse_response = client.get("/browse")

    assert mine_response.status_code == 200
    assert "Waiting for a match" in mine_response.text
    assert browse_response.status_code == 200
    assert "web-form-rider" in browse_response.text
    # Privacy: neither page is anything but the coarse/no-contact view --
    # never the precise coordinates or contact submitted above.
    for page in (mine_response.text, browse_response.text):
        assert "555-0100-secret" not in page
        assert str(FAIRFAX[0]) not in page
        assert str(FAIRFAX[1]) not in page


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


def test_non_numeric_seats_needed_reprompts_form_instead_of_a_raw_422():
    # seats_needed used to be typed `int = Form(1)` directly on the route --
    # FastAPI/pydantic coerced it to int *before* submit_new_request() (and
    # its own try/except) ever ran, so a non-numeric value never reached
    # this endpoint's own error handling. Confirmed real, not theoretical,
    # before this fix: this exact payload returned a bare
    # `{"detail":[{"type":"int_parsing",...}]}` JSON body, not the form
    # page every other bad field on this form re-renders with its own
    # "Couldn't post that request: ..." message.
    form_data = _one_off_form("seats-garbage-rider")
    form_data["seats_needed"] = "abc"

    with TestClient(app) as client:
        response = client.post("/new", data=form_data, follow_redirects=False)
        browse_response = client.get("/browse")

    assert response.status_code == 400
    assert response.headers["content-type"].startswith("text/html")
    assert "Couldn" in response.text and "post that request" in response.text
    assert "seats-garbage-rider" not in browse_response.text


def test_blank_seats_needed_still_defaults_to_one():
    # Same fix as above, but for the "cleared the number field entirely"
    # case rather than a non-numeric one -- this one should keep working
    # exactly like it did when seats_needed was `int = Form(1)`, not start
    # rejecting a blank field as a mistake.
    form_data = _one_off_form("seats-blank-rider")
    form_data["seats_needed"] = ""

    with TestClient(app) as client:
        response = client.post("/new", data=form_data, follow_redirects=False)
        assert response.status_code == 303

        browse_response = client.get("/browse")

    assert "seats-blank-rider" in browse_response.text
    assert "1 seat(s)" in browse_response.text


def test_non_numeric_weekday_reprompts_form_instead_of_a_raw_422():
    # Same underlying bug as seats_needed above, just on `weekdays` (it was
    # `list[int] = Form([])`) -- confirmed real the same way: weekdays=
    # ["abc"] 422'd with FastAPI's raw JSON body instead of this form's own
    # error page before this fix.
    form_data = {
        "rider_id": "weekday-garbage-rider",
        "origin_place": "Fairfax",
        "origin_lat": str(FAIRFAX[0]),
        "origin_lng": str(FAIRFAX[1]),
        "destination_place": "Aldie",
        "destination_lat": str(ALDIE[0]),
        "destination_lng": str(ALDIE[1]),
        "schedule_type": "recurring",
        "weekdays": ["abc"],
        "earliest_departure_time": "09:00",
        "latest_departure_time": "09:30",
        "seats_needed": "1",
        "contact": "555-0300",
    }

    with TestClient(app) as client:
        response = client.post("/new", data=form_data, follow_redirects=False)
        browse_response = client.get("/browse")

    assert response.status_code == 400
    assert response.headers["content-type"].startswith("text/html")
    assert "Couldn" in response.text and "post that request" in response.text
    assert "weekday-garbage-rider" not in browse_response.text


def test_recurring_form_recheck_shows_the_right_weekday_boxes_after_an_unrelated_error():
    # weekdays is now taken in as list[str] (see the fix above) -- this
    # proves the checkbox re-check in new_request.html (`day|string in
    # form.weekdays`) still lines up correctly with that string-typed form
    # state, for a failure that has nothing to do with weekdays at all
    # (a bad geocode here), not just that a well-formed recurring
    # submission still succeeds.
    form_data = {
        "rider_id": "recurring-recheck-rider",
        "origin_place": "Nowhereville",
        "origin_lat": "",
        "origin_lng": "",
        "destination_place": "Aldie",
        "destination_lat": str(ALDIE[0]),
        "destination_lng": str(ALDIE[1]),
        "schedule_type": "recurring",
        "weekdays": ["1", "3"],
        "earliest_departure_time": "09:00",
        "latest_departure_time": "09:30",
        "seats_needed": "1",
        "contact": "555-0400",
    }

    with TestClient(app) as client:
        response = client.post("/new", data=form_data, follow_redirects=False)

    assert response.status_code == 400
    checked_values = re.findall(r'value="(\d)"\s*checked', response.text)
    assert checked_values == ["1", "3"]


def test_missing_rider_id_field_entirely_reprompts_form_instead_of_a_raw_422():
    # rider_id/origin_place/destination_place/schedule_type/contact used to
    # be typed `str = Form(...)` -- a *required* Form field -- which meant
    # FastAPI 422'd with its own raw JSON body before submit_new_request()
    # (and its own try/except below) ever ran, the same inconsistent-error-
    # path shape as seats_needed/weekdays' own fix above, just for a field
    # left out of the request entirely instead of present-but-malformed.
    # Confirmed real, not theoretical, before this fix: leaving rider_id out
    # of the form body altogether returned a bare
    # `{"detail":[{"type":"missing",...}]}` JSON body, not this form's own
    # "Couldn't post that request: ..." page.
    form_data = _one_off_form("unused-rider-id")
    del form_data["rider_id"]

    with TestClient(app) as client:
        response = client.post("/new", data=form_data, follow_redirects=False)
        browse_response = client.get("/browse")

    assert response.status_code == 400
    assert response.headers["content-type"].startswith("text/html")
    assert "Couldn" in response.text and "post that request" in response.text
    assert "unused-rider-id" not in browse_response.text


def test_missing_contact_field_entirely_reprompts_form_instead_of_a_raw_422():
    # Same fix as rider_id above, on `contact` instead.
    form_data = _one_off_form("contact-missing-rider")
    del form_data["contact"]

    with TestClient(app) as client:
        response = client.post("/new", data=form_data, follow_redirects=False)
        browse_response = client.get("/browse")

    assert response.status_code == 400
    assert response.headers["content-type"].startswith("text/html")
    assert "Couldn" in response.text and "post that request" in response.text
    assert "contact-missing-rider" not in browse_response.text


def test_missing_origin_place_field_entirely_reprompts_form_instead_of_a_raw_422():
    # Same fix as rider_id above, on `origin_place` instead -- a missing
    # place name also leaves origin_lat/origin_lng unset for any real
    # client (they're only ever filled in by app.js's own geocode lookup
    # against this exact field), so this lands on the existing "could not
    # resolve" check rather than crashing on the missing field itself.
    form_data = _one_off_form("origin-place-missing-rider")
    del form_data["origin_place"]
    form_data["origin_lat"] = ""
    form_data["origin_lng"] = ""

    with TestClient(app) as client:
        response = client.post("/new", data=form_data, follow_redirects=False)
        browse_response = client.get("/browse")

    assert response.status_code == 400
    assert response.headers["content-type"].startswith("text/html")
    assert "Could not resolve pickup place" in response.text
    assert "origin-place-missing-rider" not in browse_response.text


def test_missing_destination_place_field_entirely_reprompts_form_instead_of_a_raw_422():
    # Same fix as rider_id above, on `destination_place` instead.
    form_data = _one_off_form("destination-place-missing-rider")
    del form_data["destination_place"]
    form_data["destination_lat"] = ""
    form_data["destination_lng"] = ""

    with TestClient(app) as client:
        response = client.post("/new", data=form_data, follow_redirects=False)
        browse_response = client.get("/browse")

    assert response.status_code == 400
    assert response.headers["content-type"].startswith("text/html")
    assert "Could not resolve destination place" in response.text
    assert "destination-place-missing-rider" not in browse_response.text


def test_missing_schedule_type_field_entirely_still_posts_as_one_off():
    # Same fix as rider_id above, on `schedule_type` instead -- but unlike
    # the other four fields, a missing schedule_type isn't itself a reason
    # to reject the request: this endpoint already treats any value that
    # isn't literally "recurring" as one-off, so a missing one falls
    # through to that exact same existing branch rather than needing its
    # own new error case.
    form_data = _one_off_form("schedule-type-missing-rider")
    del form_data["schedule_type"]

    with TestClient(app) as client:
        response = client.post("/new", data=form_data, follow_redirects=False)
        assert response.status_code == 303

        browse_response = client.get("/browse")

    assert "schedule-type-missing-rider" in browse_response.text

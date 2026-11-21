"""Mocked unit tests for TASKS.md #10's geocoding module.

Per that task's decision, automated runs never call the real Nominatim
endpoint (this sandbox's network policy denies it outright) -- these tests
mock httpx.get to prove the request-shaping and error-handling logic is
correct. The real endpoint is verified by hand in an interactive session.
"""

import threading
import time
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.geocoding import (
    MIN_SECONDS_BETWEEN_REQUESTS,
    USER_AGENT,
    PlaceNotFoundError,
    geocode_place,
)
from app.main import app
from app.schemas import Location


def _fake_response(payload: list[dict]) -> MagicMock:
    response = MagicMock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


@patch("app.geocoding._wait_for_rate_limit")
@patch("app.geocoding.httpx.get")
def test_geocode_place_resolves_known_place(mock_get, mock_wait):
    mock_get.return_value = _fake_response(
        [{"lat": "38.8462", "lon": "-77.3064"}]  # GMU, Fairfax, VA
    )

    location = geocode_place("George Mason University")

    assert location == Location(lat=38.8462, lng=-77.3064)
    mock_wait.assert_called_once()


@patch("app.geocoding._wait_for_rate_limit")
@patch("app.geocoding.httpx.get")
def test_geocode_place_sends_identifying_user_agent_and_virginia_bounds(mock_get, mock_wait):
    mock_get.return_value = _fake_response([{"lat": "38.9", "lon": "-77.4"}])

    geocode_place("Fairfax Corner")

    _, kwargs = mock_get.call_args
    assert kwargs["headers"]["User-Agent"] == USER_AGENT
    assert "browser" not in USER_AGENT.lower()
    assert kwargs["params"]["bounded"] == 1
    assert kwargs["params"]["viewbox"]


@patch("app.geocoding._wait_for_rate_limit")
@patch("app.geocoding.httpx.get")
def test_geocode_place_raises_clear_error_when_unrecognized(mock_get, mock_wait):
    mock_get.return_value = _fake_response([])

    with pytest.raises(PlaceNotFoundError):
        geocode_place("Definitely Not A Real Place XYZ")


@patch("app.geocoding.httpx.get")
def test_geocode_place_rejects_empty_input_without_calling_api(mock_get):
    with pytest.raises(PlaceNotFoundError):
        geocode_place("   ")

    mock_get.assert_not_called()


@patch("app.geocoding._wait_for_rate_limit")
@patch("app.geocoding.httpx.get")
def test_geocode_place_raises_clear_error_on_an_out_of_range_coordinate(mock_get, mock_wait):
    # Nominatim is a real third-party service this sandbox can't call for
    # real (see this file's module docstring) -- so a malformed or garbage
    # result is a real possibility this code has to handle itself, not
    # something upstream validation can be trusted to rule out. Without a
    # fix, Location(lat=999.0, ...)'s own ge/le validation raised a bare
    # pydantic ValidationError straight out of geocode_place(), which
    # app/router.py's GET /geocode only catches PlaceNotFoundError for --
    # so this surfaced as an unhandled 500, not the "clear error, never a
    # guessed location" this function's own docstring promises.
    mock_get.return_value = _fake_response([{"lat": "999.0", "lon": "-500.0"}])

    with pytest.raises(PlaceNotFoundError):
        geocode_place("Somewhere")


@patch("app.geocoding._wait_for_rate_limit")
@patch("app.geocoding.httpx.get")
def test_geocode_place_raises_clear_error_on_a_non_numeric_coordinate(mock_get, mock_wait):
    # Same gap as the out-of-range case above, but hitting float()'s own
    # ValueError instead of Location's validator -- a non-numeric "lat"/
    # "lon" string from a malformed upstream result crashed the same way.
    mock_get.return_value = _fake_response([{"lat": "not-a-number", "lon": "-77.3"}])

    with pytest.raises(PlaceNotFoundError):
        geocode_place("Somewhere else")


@patch("app.geocoding._wait_for_rate_limit")
@patch("app.geocoding.httpx.get")
def test_geocode_place_propagates_http_errors_instead_of_a_silent_wrong_match(mock_get, mock_wait):
    response = MagicMock()
    response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "boom", request=MagicMock(), response=MagicMock(status_code=503)
    )
    mock_get.return_value = response

    with pytest.raises(httpx.HTTPStatusError):
        geocode_place("Reston")


def test_rate_limit_waits_at_least_one_second_between_real_calls():
    import app.geocoding as geocoding

    geocoding._last_request_at = 0.0
    # Two monotonic() reads per call (elapsed check, then recording the
    # call): first call is "far" from t=0 so it doesn't wait; second call
    # lands 0.2s after the first, so it should sleep the remaining 0.8s.
    with patch(
        "app.geocoding.time.monotonic", side_effect=[100.0, 100.0, 100.2, 100.4]
    ), patch("app.geocoding.time.sleep") as mock_sleep:
        geocoding._wait_for_rate_limit()
        geocoding._wait_for_rate_limit()

        mock_sleep.assert_called_once()
        (waited,), _ = mock_sleep.call_args
        assert waited == pytest.approx(MIN_SECONDS_BETWEEN_REQUESTS - 0.2)


def test_rate_limit_keeps_concurrent_callers_spaced_out_too():
    # GET /geocode is a sync route, so Starlette can run two calls to
    # _wait_for_rate_limit() on two different threadpool threads at once --
    # the single-threaded test above (test_rate_limit_waits_at_least_one_
    # second_between_real_calls) can't catch a race that only shows up
    # under real concurrency. Without app.geocoding._rate_limit_lock, every
    # thread here reads the same stale _last_request_at, computes the same
    # "elapsed", and proceeds without waiting on each other -- landing all
    # their real calls within a few milliseconds of each other instead of
    # MIN_SECONDS_BETWEEN_REQUESTS apart.
    import app.geocoding as geocoding

    original_min = geocoding.MIN_SECONDS_BETWEEN_REQUESTS
    test_min = 0.2
    geocoding.MIN_SECONDS_BETWEEN_REQUESTS = test_min
    # A "previous call" recent enough that every thread below has to wait
    # at least a little -- the stale-read race only bites when there's a
    # real wait to race over (every thread reading "elapsed >= the
    # minimum" would correctly proceed immediately with or without a lock).
    geocoding._last_request_at = time.monotonic() - 0.15
    try:
        call_times: list[float] = []
        lock = threading.Lock()
        barrier = threading.Barrier(5)

        def worker() -> None:
            barrier.wait()
            geocoding._wait_for_rate_limit()
            with lock:
                call_times.append(time.monotonic())

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    finally:
        geocoding.MIN_SECONDS_BETWEEN_REQUESTS = original_min

    call_times.sort()
    gaps = [b - a for a, b in zip(call_times, call_times[1:])]
    assert all(gap >= test_min for gap in gaps)


@patch("app.router.geocode_place")
def test_geocode_endpoint_returns_location_for_known_place(mock_geocode_place):
    mock_geocode_place.return_value = Location(lat=38.8462, lng=-77.3064)

    with TestClient(app) as client:
        response = client.get("/geocode", params={"q": "George Mason University"})

    assert response.status_code == 200
    assert response.json() == {"lat": 38.8462, "lng": -77.3064}
    mock_geocode_place.assert_called_once_with("George Mason University")


@patch("app.router.geocode_place")
def test_geocode_endpoint_404s_with_clear_error_for_unrecognized_place(mock_geocode_place):
    mock_geocode_place.side_effect = PlaceNotFoundError("no match for 'Nowhereville'")

    with TestClient(app) as client:
        response = client.get("/geocode", params={"q": "Nowhereville"})

    assert response.status_code == 404
    assert "Nowhereville" in response.json()["detail"]


@patch("app.router.geocode_place")
def test_geocode_endpoint_503s_instead_of_a_raw_500_on_a_nominatim_error_status(
    mock_geocode_place,
):
    # geocode_place() deliberately propagates a real HTTP failure from
    # Nominatim rather than swallowing it into a silently wrong match (see
    # test_geocode_place_propagates_http_errors_instead_of_a_silent_wrong_match
    # above) -- but this route used to only catch PlaceNotFoundError, so
    # that propagated exception reached the caller as a bare, unhandled 500
    # indistinguishable from an actual server bug.
    mock_geocode_place.side_effect = httpx.HTTPStatusError(
        "boom",
        request=httpx.Request("GET", "https://nominatim.openstreetmap.org/search"),
        response=httpx.Response(
            503, request=httpx.Request("GET", "https://nominatim.openstreetmap.org/search")
        ),
    )

    with TestClient(app) as client:
        response = client.get("/geocode", params={"q": "Reston"})

    assert response.status_code == 503
    assert "temporarily unavailable" in response.json()["detail"]


@patch("app.router.geocode_place")
def test_geocode_endpoint_503s_instead_of_a_raw_500_on_a_nominatim_timeout(mock_geocode_place):
    # Same gap as the error-status case above, but hit via a transport-level
    # failure (httpx.ConnectTimeout, an httpx.RequestError subclass) instead
    # of a bad response status -- a timeout never even reaches
    # raise_for_status(), so it's a genuinely different code path through
    # geocode_place(), not just a different exception value.
    mock_geocode_place.side_effect = httpx.ConnectTimeout("timed out")

    with TestClient(app) as client:
        response = client.get("/geocode", params={"q": "Reston"})

    assert response.status_code == 503
    assert "temporarily unavailable" in response.json()["detail"]

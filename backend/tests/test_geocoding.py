"""Mocked unit tests for TASKS.md #10's geocoding module.

Per that task's decision, automated runs never call the real Nominatim
endpoint (this sandbox's network policy denies it outright) -- these tests
mock httpx.get to prove the request-shaping and error-handling logic is
correct. The real endpoint is verified by hand in an interactive session.
"""

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

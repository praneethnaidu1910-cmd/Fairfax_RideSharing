"""app/main.py's RequestValidationError handler -- the fix for a real
crash in how FastAPI's own default 422 handler reports a NaN/Infinity
value that failed a numeric Field(ge=.., le=..) check.

Python's own json.loads() (what Starlette's Request.json() uses to parse
a request body) accepts the non-standard `NaN`/`Infinity`/`-Infinity`
tokens as valid float literals, unlike strict JSON -- so a request body
containing one of these parses cleanly, reaches pydantic as a real
float('nan')/float('inf'), and correctly fails Location's lat/lng bounds
(any comparison against NaN is False, so it's never mistaken for a value
inside -90..90/-180..180). But FastAPI's default handler echoes the exact
failing value back as error['input'] (the same thing it does for any
other bad value, e.g. lat=999), and Starlette's JSONResponse renders with
json.dumps(..., allow_nan=False) -- deliberately strict, since a literal
NaN/Infinity isn't valid JSON for any other caller to parse back. Before
this fix, that combination didn't 422 at all: it crashed while building
the error response itself, well past the point a 422 would normally have
already gone out. See app.main._json_safe's own docstring for the full
live reproduction.
"""

from fastapi.testclient import TestClient

from app.main import _json_safe, app


def test_json_safe_leaves_ordinary_values_untouched():
    assert _json_safe({"a": 1, "b": [2, 3.5, "x"], "c": None}) == {
        "a": 1,
        "b": [2, 3.5, "x"],
        "c": None,
    }


def test_json_safe_replaces_nan_and_infinity_with_their_str_at_any_depth():
    sanitized = _json_safe(
        {
            "input": float("nan"),
            "nested": {"input": float("inf")},
            "list": [float("-inf"), 1.0],
        }
    )
    assert sanitized == {
        "input": "nan",
        "nested": {"input": "inf"},
        "list": ["-inf", 1.0],
    }


def test_create_request_rejects_a_nan_coordinate_instead_of_crashing_the_response():
    # Valid Python-flavored JSON (json.loads accepts "NaN"), invalid
    # strict JSON, and -- before this fix -- a crash while building the
    # 422 this should have been all along.
    body = (
        '{"rider_id": "rider-nan-coord", '
        '"origin": {"lat": NaN, "lng": -77.3064}, '
        '"destination": {"lat": 38.9757, "lng": -77.6122}, '
        '"schedule": {"earliest_departure": "2026-12-01T09:00:00", '
        '"latest_departure": "2026-12-01T09:30:00"}, '
        '"seats_needed": 1, "contact": "555-0000"}'
    )

    with TestClient(app) as client:
        response = client.post(
            "/requests", content=body, headers={"Content-Type": "application/json"}
        )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert any(error["loc"][-1] == "lat" and error["input"] == "nan" for error in detail)


def test_create_request_rejects_an_infinite_coordinate_instead_of_crashing_the_response():
    body = (
        '{"rider_id": "rider-inf-coord", '
        '"origin": {"lat": 38.8462, "lng": -Infinity}, '
        '"destination": {"lat": 38.9757, "lng": -77.6122}, '
        '"schedule": {"earliest_departure": "2026-12-01T09:00:00", '
        '"latest_departure": "2026-12-01T09:30:00"}, '
        '"seats_needed": 1, "contact": "555-0000"}'
    )

    with TestClient(app) as client:
        response = client.post(
            "/requests", content=body, headers={"Content-Type": "application/json"}
        )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert any(error["loc"][-1] == "lng" and error["input"] == "-inf" for error in detail)

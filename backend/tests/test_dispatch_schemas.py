import pytest
from pydantic import ValidationError

from app.dispatch.schemas import Location


@pytest.mark.parametrize(
    "lat,lng",
    [
        (999.0, -77.3064),  # out-of-range latitude
        (38.8462, -500.0),  # out-of-range longitude
        (90.1, 0.0),  # just past the real-world pole boundary
        (-90.1, 0.0),
        (0.0, 180.1),
        (0.0, -180.1),
    ],
)
def test_location_rejects_out_of_range_coordinates(lat, lng):
    # Same bug, same fix as app/schemas.py's Location (see
    # tests/test_schemas.py): without range validation, an impossible
    # point like lat=999 was silently accepted and fed straight into
    # app/dispatch/matching.py's haversine_miles() -- math.sin/cos don't
    # care that 999 isn't a real latitude, so a typo'd rider_location
    # would quietly compute a nonsense distance instead of getting
    # rejected at intake.
    with pytest.raises(ValidationError):
        Location(lat=lat, lng=lng)


def test_location_accepts_boundary_coordinates():
    # The real-world edges themselves (poles, antimeridian) are valid and
    # must not be rejected by an off-by-one bound.
    Location(lat=90.0, lng=180.0)
    Location(lat=-90.0, lng=-180.0)

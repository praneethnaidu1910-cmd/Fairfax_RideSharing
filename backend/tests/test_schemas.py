from datetime import datetime, time, timedelta

import pytest
from pydantic import ValidationError

from app.sample_data import SAMPLE_REQUESTS
from app.schemas import (
    Location,
    OneOffSchedule,
    RecurringSchedule,
    RequestStatus,
    RideRequest,
    RideRequestCreate,
)


def _one_off_schedule() -> OneOffSchedule:
    return OneOffSchedule(
        earliest_departure=datetime.utcnow(),
        latest_departure=datetime.utcnow() + timedelta(minutes=30),
    )


def test_ride_request_with_one_off_schedule_validates():
    req = RideRequest(
        rider_id="rider-1",
        origin=Location(lat=38.8462, lng=-77.3064),  # Fairfax, VA
        destination=Location(lat=38.9586, lng=-77.3570),  # Reston, VA
        schedule=_one_off_schedule(),
        seats_needed=2,
        contact="555-0100",
    )
    assert req.seats_needed == 2
    assert req.id is not None
    assert isinstance(req.schedule, OneOffSchedule)
    assert req.status == RequestStatus.OPEN


def test_ride_request_with_recurring_schedule_validates():
    req = RideRequest(
        rider_id="rider-2",
        origin=Location(lat=38.8965, lng=-77.4318),  # Chantilly, VA
        destination=Location(lat=38.9586, lng=-77.3570),  # Reston, VA
        schedule=RecurringSchedule(
            weekdays=[0, 1, 2, 3, 4],
            earliest_departure_time=time(9, 0),
            latest_departure_time=time(9, 30),
        ),
        contact="555-0101",
    )
    assert isinstance(req.schedule, RecurringSchedule)
    assert req.schedule.weekdays == [0, 1, 2, 3, 4]


def test_one_off_schedule_rejects_inverted_window():
    with pytest.raises(ValidationError):
        OneOffSchedule(
            earliest_departure=datetime.utcnow(),
            latest_departure=datetime.utcnow() - timedelta(minutes=1),
        )


def test_recurring_schedule_rejects_invalid_weekday():
    with pytest.raises(ValidationError):
        RecurringSchedule(
            weekdays=[7],
            earliest_departure_time=time(9, 0),
            latest_departure_time=time(9, 30),
        )


def test_recurring_schedule_rejects_empty_weekdays():
    with pytest.raises(ValidationError):
        RecurringSchedule(
            weekdays=[],
            earliest_departure_time=time(9, 0),
            latest_departure_time=time(9, 30),
        )


def test_contact_present_on_model_but_not_required_serialized_elsewhere():
    # Flags the field per TASKS.md #1; excluding it from pre-match API
    # responses is task 6's response-shaping work, not tested here.
    req = RideRequest(
        rider_id="rider-3",
        origin=Location(lat=38.8462, lng=-77.3064),
        destination=Location(lat=38.9586, lng=-77.3570),
        schedule=_one_off_schedule(),
        contact="555-0102",
    )
    assert req.contact == "555-0102"
    assert "contact" in req.model_dump()


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
    # Without range validation, an impossible point like lat=999 was
    # silently accepted and fed straight into app/geo.py's haversine/
    # bearing math (no error -- math.sin/cos don't care that 999 isn't a
    # real latitude), so a client typo or a bad geocoding parse would
    # quietly produce nonsense match scores instead of a clear rejection.
    with pytest.raises(ValidationError):
        Location(lat=lat, lng=lng)


def test_location_accepts_boundary_coordinates():
    # The real-world edges themselves (poles, antimeridian) are valid and
    # must not be rejected by an off-by-one bound.
    Location(lat=90.0, lng=180.0)
    Location(lat=-90.0, lng=-180.0)


def test_coarse_cell_is_stable_h3_index():
    loc = Location(lat=38.8462, lng=-77.3064)
    cell = loc.coarse_cell()
    assert isinstance(cell, str)
    assert cell == loc.coarse_cell()


def test_sample_data_loads_and_validates():
    assert len(SAMPLE_REQUESTS) > 0
    assert all(isinstance(r, RideRequest) for r in SAMPLE_REQUESTS)


def test_sample_data_has_both_schedule_kinds():
    assert any(isinstance(r.schedule, OneOffSchedule) for r in SAMPLE_REQUESTS)
    assert any(isinstance(r.schedule, RecurringSchedule) for r in SAMPLE_REQUESTS)


def test_sample_data_has_both_stranger_and_group_requests():
    assert any(r.seats_needed == 1 for r in SAMPLE_REQUESTS)
    assert any(r.seats_needed > 1 for r in SAMPLE_REQUESTS)


def _create_payload(**overrides):
    base = dict(
        rider_id="rider-x",
        origin=Location(lat=38.8462, lng=-77.3064),
        destination=Location(lat=38.9586, lng=-77.3570),
        schedule=_one_off_schedule(),
        contact="555-0199",
    )
    base.update(overrides)
    return base


@pytest.mark.parametrize("field", ["rider_id", "contact"])
def test_ride_request_create_rejects_empty_rider_id_or_contact(field):
    # Without this, an empty contact reached a real match untouched --
    # the matched counterpart's reveal would show nothing to actually
    # contact, silently defeating SCOPE.md's whole stated reason for
    # collecting this field. RideRequest itself (the stored/internal
    # shape) deliberately keeps no such constraint, since it also has to
    # represent an already-anonymized row (TASKS.md #17) whose `contact`
    # was intentionally blanked to "" -- the constraint only belongs at
    # this intake boundary.
    with pytest.raises(ValidationError):
        RideRequestCreate(**_create_payload(**{field: ""}))


@pytest.mark.parametrize("field", ["rider_id", "contact"])
@pytest.mark.parametrize("blank", [" ", "   ", "\t", "\n "])
def test_ride_request_create_rejects_whitespace_only_rider_id_or_contact(field, blank):
    # Field(min_length=1) alone isn't enough -- a whitespace-only string
    # has length >= 1, so it sailed through the fix above untouched.
    # Confirmed this was real: RideRequestCreate(rider_id="   ", ...,
    # contact="   ") validated cleanly before this test existed, and a
    # live POST /requests with the same payload returned 201 -- the exact
    # "Matched! Your ride partner, :" / blank Contact line gap the
    # non-empty fix above was supposed to close, just one whitespace
    # character away from it.
    with pytest.raises(ValidationError):
        RideRequestCreate(**_create_payload(**{field: blank}))


def test_ride_request_create_keeps_incidental_surrounding_whitespace_on_a_real_value():
    # The fix rejects blank-after-stripping input, but doesn't itself
    # strip a value that has real content -- "John" typed with a stray
    # leading/trailing space is still "John", not an error.
    req = RideRequestCreate(**_create_payload(rider_id=" John "))
    assert req.rider_id == " John "


def test_ride_request_itself_still_accepts_an_anonymized_blank_contact():
    # app/store.py's _from_orm() reconstructs a RideRequest straight from
    # a stored row, including an already-anonymized one -- this must keep
    # working after the intake-side fix above.
    req = RideRequest(
        rider_id="rider-anonymized",
        origin=Location(lat=38.8462, lng=-77.3064),
        destination=Location(lat=38.9586, lng=-77.3570),
        schedule=_one_off_schedule(),
        contact="",
    )
    assert req.contact == ""

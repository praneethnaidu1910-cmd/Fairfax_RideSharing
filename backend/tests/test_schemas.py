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

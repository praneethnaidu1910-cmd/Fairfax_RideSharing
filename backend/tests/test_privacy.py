from datetime import datetime, time, timedelta

from app.privacy import FUZZ_PADDING, fuzz_schedule, to_public
from app.schemas import Location, OneOffSchedule, RecurringSchedule, RequestStatus, RideRequest


def test_fuzz_schedule_widens_one_off_window_on_both_ends():
    now = datetime.utcnow()
    schedule = OneOffSchedule(earliest_departure=now, latest_departure=now + timedelta(minutes=30))

    fuzzed = fuzz_schedule(schedule)

    assert fuzzed.earliest_departure == now - FUZZ_PADDING
    assert fuzzed.latest_departure == now + timedelta(minutes=30) + FUZZ_PADDING


def test_fuzz_schedule_widens_recurring_window_on_both_ends():
    schedule = RecurringSchedule(
        weekdays=[0, 1, 2], earliest_departure_time=time(9, 0), latest_departure_time=time(9, 30)
    )

    fuzzed = fuzz_schedule(schedule)

    assert fuzzed.weekdays == [0, 1, 2]
    assert fuzzed.earliest_departure_time == time(8, 45)
    assert fuzzed.latest_departure_time == time(9, 45)


def test_fuzz_schedule_clamps_recurring_window_at_midnight_instead_of_wrapping():
    # Regression: _shift_time used to combine the bare time with a
    # throwaway date, shift it, then drop the date again -- so an
    # earliest_departure_time within FUZZ_PADDING of midnight (e.g. 00:05)
    # wrapped around to the *previous* day's 23:50, which then read as
    # later than a same-day latest_departure_time and blew up
    # RecurringSchedule's own "latest must not be before earliest"
    # validator the moment anyone browsed a request with an early-morning
    # recurring window. Widening should clamp at the day boundary instead
    # of producing an invalid, crossed-over schedule.
    early_morning = RecurringSchedule(
        weekdays=[0, 1, 2, 3, 4],
        earliest_departure_time=time(0, 5),
        latest_departure_time=time(9, 0),
    )
    fuzzed_early = fuzz_schedule(early_morning)
    assert fuzzed_early.earliest_departure_time == time(0, 0)
    assert fuzzed_early.latest_departure_time == time(9, 15)

    late_night = RecurringSchedule(
        weekdays=[0, 1, 2, 3, 4],
        earliest_departure_time=time(9, 0),
        latest_departure_time=time(23, 50),
    )
    fuzzed_late = fuzz_schedule(late_night)
    assert fuzzed_late.earliest_departure_time == time(8, 45)
    assert fuzzed_late.latest_departure_time == time(23, 59, 59, 999999)


def test_to_public_never_includes_contact_or_precise_location():
    schedule = OneOffSchedule(
        earliest_departure=datetime.utcnow() + timedelta(hours=1),
        latest_departure=datetime.utcnow() + timedelta(hours=2),
    )
    request = RideRequest(
        rider_id="rider-x",
        origin=Location(lat=38.8462, lng=-77.3064),
        destination=Location(lat=38.9757, lng=-77.6122),
        schedule=schedule,
        contact="555-0199",
    )

    public = to_public(request)

    assert "contact" not in public.model_dump()
    assert "555-0199" not in public.model_dump_json()
    assert "38.8462" not in public.model_dump_json()


def test_to_public_reports_expired_for_a_still_open_past_window_recurring_schedule_edge():
    # A still-OPEN request whose window has passed reads as expired here
    # even though nothing ever flips the stored status (TASKS.md #14).
    past_schedule = OneOffSchedule(
        earliest_departure=datetime.utcnow() - timedelta(hours=2),
        latest_departure=datetime.utcnow() - timedelta(hours=1),
    )
    request = RideRequest(
        rider_id="rider-y",
        origin=Location(lat=38.8462, lng=-77.3064),
        destination=Location(lat=38.9757, lng=-77.6122),
        schedule=past_schedule,
        contact="555-0200",
    )
    assert request.status == RequestStatus.OPEN

    public = to_public(request)

    assert public.status == RequestStatus.EXPIRED

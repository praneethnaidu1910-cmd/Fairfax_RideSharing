from datetime import datetime, time, timedelta

from app.privacy import FUZZ_PADDING, fuzz_schedule, to_list_item, to_public
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


def test_fuzz_schedule_clamps_one_off_window_at_the_datetime_range_instead_of_overflowing():
    # Regression: nothing in OneOffSchedule's own validator bounds how far
    # in the past or future earliest_departure/latest_departure can be --
    # only that the two fields are naive and correctly ordered. A schedule
    # within FUZZ_PADDING of either end of the datetime range Python can
    # represent at all used to crash fuzz_schedule() itself with a bare
    # OverflowError (schedule.earliest_departure - FUZZ_PADDING, or
    # schedule.latest_departure + FUZZ_PADDING, stepping past
    # datetime.min/datetime.max), not a clean result -- and since
    # create_request() (app/router.py) already calls to_public() -> this
    # function for its own response, this crashed the very POST /requests
    # call that created the request, not just a later GET.
    near_the_beginning_of_time = OneOffSchedule(
        earliest_departure=datetime(1, 1, 1, 0, 5, 0),
        latest_departure=datetime(1, 1, 1, 0, 10, 0),
    )
    fuzzed_early = fuzz_schedule(near_the_beginning_of_time)
    assert fuzzed_early.earliest_departure == datetime.min
    assert fuzzed_early.latest_departure == datetime(1, 1, 1, 0, 25, 0)

    near_the_end_of_time = OneOffSchedule(
        earliest_departure=datetime(9999, 12, 31, 23, 50, 0),
        latest_departure=datetime(9999, 12, 31, 23, 55, 0),
    )
    fuzzed_late = fuzz_schedule(near_the_end_of_time)
    assert fuzzed_late.earliest_departure == datetime(9999, 12, 31, 23, 35, 0)
    assert fuzzed_late.latest_departure == datetime.max


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


def test_to_list_item_never_includes_id_contact_or_precise_location():
    # Regression: to_public() (id included) used to be what GET /requests'
    # open list returned too -- handing every open request's id to any
    # anonymous caller, no auth required, which is the one piece of
    # information GET /requests/{id}?viewer_request_id= (TASKS.md #7)
    # treats as a secret only a request's own poster/matched counterpart
    # should ever have. to_list_item() is the shape that's actually safe
    # to show someone who didn't ask for this request by id.
    schedule = OneOffSchedule(
        earliest_departure=datetime.utcnow() + timedelta(hours=1),
        latest_departure=datetime.utcnow() + timedelta(hours=2),
    )
    request = RideRequest(
        rider_id="rider-list-item",
        origin=Location(lat=38.8462, lng=-77.3064),
        destination=Location(lat=38.9757, lng=-77.6122),
        schedule=schedule,
        contact="555-0299",
    )

    item = to_list_item(request)
    dumped = item.model_dump()

    assert "id" not in dumped
    assert "contact" not in dumped
    assert "555-0299" not in item.model_dump_json()
    assert "38.8462" not in item.model_dump_json()
    assert dumped["rider_id"] == "rider-list-item"

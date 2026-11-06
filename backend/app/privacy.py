"""Response-shaping for pre-match visibility (TASKS.md #6, SCOPE.md: "no
exact address, ever, pre-match" / "fuzzed time window").

Kept out of app/schemas.py so that module doesn't need app.geo's H3 helper
beyond what Location.coarse_cell() already wraps -- to_public() is the one
place that turns a full RideRequest into the coarse/fuzzed shape everyone
except the two matched parties gets to see (task 7 is the exception path).
"""

from datetime import date, datetime, time, timedelta
from typing import Union

from app.matching.scoring import is_expired
from app.schemas import (
    OneOffSchedule,
    RecurringSchedule,
    RequestStatus,
    RideRequest,
    RideRequestPublic,
)

# Widen every departure window by this much on each side so the fuzzed
# window never reveals the real one exactly, even when the real window is
# already this narrow or narrower.
FUZZ_PADDING = timedelta(minutes=15)


def _shift_time(value: time, delta: timedelta) -> time:
    # time has no arithmetic of its own -- combine with a throwaway date and
    # shift. A RecurringSchedule's earliest/latest are same-day times with no
    # date attached (model_validator enforces latest >= earliest), so a shift
    # that crosses midnight has nowhere to go -- clamp to the day's own
    # boundaries instead of letting the dropped date silently wrap the time
    # back around (e.g. 00:05 - 15min becoming 23:50, which would then read
    # as *after* a same-day latest_departure_time and blow up the
    # RecurringSchedule's own validator the moment anyone browsed a request
    # with an early-morning or late-night recurring window).
    day_start = datetime.combine(date.today(), time.min)
    day_end = datetime.combine(date.today(), time.max)
    shifted = datetime.combine(date.today(), value) + delta
    return max(day_start, min(shifted, day_end)).time()


def fuzz_schedule(
    schedule: Union[OneOffSchedule, RecurringSchedule],
) -> Union[OneOffSchedule, RecurringSchedule]:
    """Same schedule shape, widened by FUZZ_PADDING on both ends."""
    if isinstance(schedule, OneOffSchedule):
        return OneOffSchedule(
            earliest_departure=schedule.earliest_departure - FUZZ_PADDING,
            latest_departure=schedule.latest_departure + FUZZ_PADDING,
        )
    return RecurringSchedule(
        weekdays=schedule.weekdays,
        earliest_departure_time=_shift_time(schedule.earliest_departure_time, -FUZZ_PADDING),
        latest_departure_time=_shift_time(schedule.latest_departure_time, FUZZ_PADDING),
    )


def to_public(request: RideRequest) -> RideRequestPublic:
    """The coarse/fuzzed view of a request -- what GET /requests returns for
    everyone. Never touches request.contact or the precise Location.

    `status` is computed, not read straight off the stored request: an
    OPEN request whose one-off window has already passed (TASKS.md #14,
    scoring.is_expired) displays as `expired` here even though nothing
    ever flips its persisted status -- SCOPE.md's "live status... without
    the poster manually re-posting" only needs this to be true of what a
    reader sees, not a stored value, so there's no background job/cron
    needed to make it happen.
    """
    status = request.status
    if status == RequestStatus.OPEN and is_expired(request):
        status = RequestStatus.EXPIRED
    return RideRequestPublic(
        id=request.id,
        rider_id=request.rider_id,
        origin_area=request.origin.coarse_cell(),
        destination_area=request.destination.coarse_cell(),
        schedule=fuzz_schedule(request.schedule),
        seats_needed=request.seats_needed,
        status=status,
        posted_at=request.posted_at,
    )

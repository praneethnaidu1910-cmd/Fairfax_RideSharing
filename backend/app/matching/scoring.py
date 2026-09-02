"""Compatibility scoring for candidate ride-request pairs.

Design: docs/MATCHING_ALGORITHM.md's "Compatibility scoring" section.
Each dimension is its own function so it's testable in isolation; a
weighted sum (compatibility_score) combines the scored dimensions into one
number for the greedy engine (TASKS.md #4) to sort on. Capacity is a hard
constraint per the design doc, not part of that sum -- callers check it
separately with capacity_fits().

Recurring schedules never reach temporal_score()/compatibility_score()
directly: expand_schedule() turns a RecurringSchedule into concrete
OneOffSchedule instances for one calendar week first, so scoring itself
only ever compares one-off windows (this stays a pre-processing step, not
new scoring logic, per TASKS.md #3).
"""

import math
from datetime import date, datetime, timedelta
from typing import Optional, Union

from app.geo import bearing_degrees, haversine_miles
from app.schemas import OneOffSchedule, RecurringSchedule, RideRequest

# Named, tunable weights (docs/MATCHING_ALGORITHM.md: "weighted sum to
# start; each weight is a named, tunable constant... so the tradeoffs are
# explainable"). Sum to 1.0 so compatibility_score stays in 0..1.
WEIGHT_SPATIAL = 0.4
WEIGHT_DIRECTIONAL = 0.35
WEIGHT_TEMPORAL = 0.25

# Beyond this, an origin/destination pair isn't "close enough to share a
# pickup" (SCOPE.md's "1.2mi apart, would walk to a shared pickup" example).
MAX_PICKUP_DISTANCE_MILES = 5.0


def spatial_score(a: RideRequest, b: RideRequest) -> float:
    """Average of normalized origin and destination closeness, 0..1."""
    origin_distance = haversine_miles(a.origin.lat, a.origin.lng, b.origin.lat, b.origin.lng)
    destination_distance = haversine_miles(
        a.destination.lat, a.destination.lng, b.destination.lat, b.destination.lng
    )
    origin_score = max(0.0, 1 - origin_distance / MAX_PICKUP_DISTANCE_MILES)
    destination_score = max(0.0, 1 - destination_distance / MAX_PICKUP_DISTANCE_MILES)
    return (origin_score + destination_score) / 2


def directional_score(a: RideRequest, b: RideRequest) -> float:
    """Cosine similarity of each request's origin->destination bearing, 0..1.

    Catches the "opposite direction" false-positive named in
    docs/MATCHING_ALGORITHM.md: same corridor, same bearing -> ~1;
    same corridor, reversed bearing (180 degrees apart) -> ~0.
    """
    bearing_a = bearing_degrees(a.origin.lat, a.origin.lng, a.destination.lat, a.destination.lng)
    bearing_b = bearing_degrees(b.origin.lat, b.origin.lng, b.destination.lat, b.destination.lng)
    cosine_similarity = math.cos(math.radians(bearing_a - bearing_b))
    return (cosine_similarity + 1) / 2


def temporal_score(a: OneOffSchedule, b: OneOffSchedule) -> float:
    """Overlap of two one-off departure windows, normalized by the shorter
    window's duration, 0..1. Zero for disjoint windows."""
    overlap_start = max(a.earliest_departure, b.earliest_departure)
    overlap_end = min(a.latest_departure, b.latest_departure)
    overlap_seconds = (overlap_end - overlap_start).total_seconds()
    if overlap_seconds <= 0:
        return 0.0
    duration_a = (a.latest_departure - a.earliest_departure).total_seconds()
    duration_b = (b.latest_departure - b.earliest_departure).total_seconds()
    shortest_window = max(min(duration_a, duration_b), 1.0)
    return min(1.0, overlap_seconds / shortest_window)


def capacity_fits(a: RideRequest, b: RideRequest, vehicle_capacity: int) -> bool:
    """Hard constraint (docs/MATCHING_ALGORITHM.md): checked separately,
    never folded into the weighted compatibility_score sum."""
    return a.seats_needed + b.seats_needed <= vehicle_capacity


def is_expired(request: RideRequest, now: Optional[datetime] = None) -> bool:
    """Whether `request`'s departure window has fully passed (SCOPE.md's
    "live status: open / matched / expired" -- TASKS.md #14).

    Only a OneOffSchedule has a single point in time it can be judged
    against (its own latest_departure); a RecurringSchedule is a standing
    weekly pattern with no stated end date in SCOPE.md, so it never
    expires here -- treating "today's occurrence already happened" as
    request-level expiry would be wrong, since tomorrow's occurrence
    hasn't. Whether/how a recurring request should ever expire is an open
    product question, not something to guess at (see TASKS.md #14's note).
    """
    if not isinstance(request.schedule, OneOffSchedule):
        return False
    now = now or datetime.utcnow()
    return now > request.schedule.latest_departure


def compatibility_score(
    a: RideRequest,
    b: RideRequest,
    window_a: OneOffSchedule,
    window_b: OneOffSchedule,
) -> float:
    """Weighted sum of the scored dimensions for one pair of one-off windows."""
    return (
        WEIGHT_SPATIAL * spatial_score(a, b)
        + WEIGHT_DIRECTIONAL * directional_score(a, b)
        + WEIGHT_TEMPORAL * temporal_score(window_a, window_b)
    )


def expand_schedule(
    schedule: Union[OneOffSchedule, RecurringSchedule],
    reference_date: Optional[date] = None,
) -> list[OneOffSchedule]:
    """Concrete one-off windows for one calendar week.

    A OneOffSchedule expands to itself (single-element list) -- already a
    one-off window, nothing to do. A RecurringSchedule expands to one
    OneOffSchedule per weekday in schedule.weekdays, all in the
    Monday-Sunday week containing reference_date (today, by default) --
    e.g. weekdays=[0, 1, 2, 3, 4] becomes 5 instances.
    """
    if isinstance(schedule, OneOffSchedule):
        return [schedule]

    reference_date = reference_date or date.today()
    week_monday = reference_date - timedelta(days=reference_date.weekday())
    instances = []
    for weekday in schedule.weekdays:
        instance_date = week_monday + timedelta(days=weekday)
        instances.append(
            OneOffSchedule(
                earliest_departure=datetime.combine(instance_date, schedule.earliest_departure_time),
                latest_departure=datetime.combine(instance_date, schedule.latest_departure_time),
            )
        )
    return instances

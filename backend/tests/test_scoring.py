from datetime import date, datetime, time, timedelta

from app.matching.scoring import (
    can_ever_be_matched,
    capacity_fits,
    compatibility_score,
    directional_score,
    expand_schedule,
    explain_match,
    is_expired,
    spatial_score,
    temporal_score,
)
from app.sample_data import SAMPLE_REQUESTS
from app.schemas import Location, OneOffSchedule, RecurringSchedule, RideRequest

# rider-1 (Fairfax -> Aldie) / rider-7 (close origin, same Aldie
# destination, overlapping window): the "known-good" pair.
RIDER_1 = SAMPLE_REQUESTS[0]
RIDER_2 = SAMPLE_REQUESTS[1]  # Aldie -> Fairfax: opposite direction of rider-1
RIDER_6 = SAMPLE_REQUESTS[5]  # Manassas -> Sterling: far from everything else
RIDER_7 = SAMPLE_REQUESTS[6]  # ~0.5mi from rider-1's origin, same destination
RIDER_4 = SAMPLE_REQUESTS[3]  # recurring, weekdays=[0,1,2,3,4], 9:00-9:30


def test_spatial_score_close_pair_scores_higher_than_far_pair():
    close_score = spatial_score(RIDER_1, RIDER_7)
    far_score = spatial_score(RIDER_1, RIDER_6)
    assert close_score > far_score


def test_directional_score_same_direction_scores_higher_than_opposite():
    same_direction = directional_score(RIDER_1, RIDER_7)
    opposite_direction = directional_score(RIDER_1, RIDER_2)
    assert same_direction > opposite_direction
    assert opposite_direction < 0.2  # near-180-degree bearing difference -> near 0


def test_temporal_score_overlapping_windows_score_higher_than_disjoint():
    now = datetime.utcnow()
    window_a = OneOffSchedule(earliest_departure=now, latest_departure=now + timedelta(minutes=30))
    overlapping = OneOffSchedule(
        earliest_departure=now + timedelta(minutes=10),
        latest_departure=now + timedelta(minutes=40),
    )
    disjoint = OneOffSchedule(
        earliest_departure=now + timedelta(hours=5),
        latest_departure=now + timedelta(hours=5, minutes=30),
    )
    assert temporal_score(window_a, overlapping) > 0
    assert temporal_score(window_a, disjoint) == 0


def test_temporal_score_precise_instant_contained_in_a_window_is_a_perfect_match():
    # A precise departure "window" that's really a single instant (latest
    # == earliest -- OneOffSchedule's own validator allows this, e.g. a
    # rider who typed the same value into both fields instead of giving
    # themselves flexibility) falling inside another rider's real window
    # used to score 0.0 overlap here -- the exact same number as two
    # requests hours apart -- because overlap_seconds collapses to 0
    # whenever one side has zero width, regardless of where that instant
    # falls. That's the worst possible score for what's actually the best
    # possible temporal fit: every acceptable moment the precise side has
    # (there's only one) is covered by the other's window.
    now = datetime.utcnow()
    precise_instant = OneOffSchedule(earliest_departure=now, latest_departure=now)
    containing_window = OneOffSchedule(
        earliest_departure=now - timedelta(minutes=15),
        latest_departure=now + timedelta(minutes=15),
    )
    outside_window = OneOffSchedule(
        earliest_departure=now + timedelta(hours=5),
        latest_departure=now + timedelta(hours=5, minutes=30),
    )
    assert temporal_score(precise_instant, containing_window) == 1.0
    assert temporal_score(precise_instant, precise_instant) == 1.0
    assert temporal_score(precise_instant, outside_window) == 0.0


def test_temporal_score_two_normal_windows_merely_touching_still_scores_zero():
    # A different, narrower case this fix deliberately leaves alone: two
    # windows that both have real width and only share a single boundary
    # instant (not one side being a precise, zero-width "window") still
    # scores 0 overlap, same as before this fix.
    now = datetime.utcnow()
    window_a = OneOffSchedule(earliest_departure=now, latest_departure=now + timedelta(minutes=30))
    touching = OneOffSchedule(
        earliest_departure=now + timedelta(minutes=30),
        latest_departure=now + timedelta(minutes=60),
    )
    assert temporal_score(window_a, touching) == 0.0


def test_capacity_fits_hard_constraint():
    assert capacity_fits(RIDER_1, RIDER_7, vehicle_capacity=4)  # 1 + 1 seats
    assert not capacity_fits(RIDER_1, RIDER_7, vehicle_capacity=1)


def test_can_ever_be_matched_true_exactly_when_the_smallest_possible_partner_fits():
    # capacity_fits() needs a.seats_needed + b.seats_needed <=
    # vehicle_capacity, and the smallest possible partner is seats_needed=1
    # (app/schemas.py's Field(ge=1)) -- so can_ever_be_matched() should
    # track exactly whether *that* partner would fit, not some other
    # threshold. Confirmed with a live check before writing the function:
    # capacity_fits() against a real seats_needed=1 partner at
    # vehicle_capacity=4 is True for seats_needed in {1, 2, 3} and False
    # for {4, 5} -- the exact boundary this asserts.
    for seats_needed in (1, 2, 3):
        request = RIDER_1.model_copy(update={"seats_needed": seats_needed})
        assert can_ever_be_matched(request, vehicle_capacity=4) is True
    for seats_needed in (4, 5):
        request = RIDER_1.model_copy(update={"seats_needed": seats_needed})
        assert can_ever_be_matched(request, vehicle_capacity=4) is False


def test_known_good_pair_scores_higher_than_known_bad_pair():
    good_score = compatibility_score(RIDER_1, RIDER_7, RIDER_1.schedule, RIDER_7.schedule)
    bad_score = compatibility_score(RIDER_1, RIDER_2, RIDER_1.schedule, RIDER_2.schedule)
    assert good_score > bad_score


def test_explain_match_states_real_distances_overlap_and_capacity():
    # SCOPE.md MVP item 6 ("for any match, the engine can state why") --
    # the explanation has to actually name the real numbers, not just
    # repeat a canned phrase.
    reason = explain_match(RIDER_1, RIDER_7, RIDER_1.schedule, RIDER_7.schedule)
    assert "mi apart" in reason
    assert "bearing difference" in reason
    assert "min window overlap" in reason
    assert "capacity fits" in reason


def test_explain_match_differs_between_a_close_and_a_far_pair():
    close_reason = explain_match(RIDER_1, RIDER_7, RIDER_1.schedule, RIDER_7.schedule)
    far_reason = explain_match(RIDER_1, RIDER_6, RIDER_1.schedule, RIDER_6.schedule)
    assert close_reason != far_reason


def _make_request(schedule) -> RideRequest:
    point = Location(lat=38.8462, lng=-77.3064)
    return RideRequest(
        rider_id="rider-x", origin=point, destination=point, schedule=schedule, contact="555-0199"
    )


def test_is_expired_true_once_latest_departure_has_passed():
    now = datetime.utcnow()
    schedule = OneOffSchedule(
        earliest_departure=now - timedelta(hours=2), latest_departure=now - timedelta(hours=1)
    )
    assert is_expired(_make_request(schedule), now=now)


def test_is_expired_false_while_window_is_still_upcoming():
    now = datetime.utcnow()
    schedule = OneOffSchedule(
        earliest_departure=now + timedelta(minutes=10), latest_departure=now + timedelta(minutes=40)
    )
    assert not is_expired(_make_request(schedule), now=now)


def test_is_expired_always_false_for_recurring_schedule():
    # A standing weekly pattern has no single point in time to judge
    # "expired" against -- TASKS.md #14's documented open question.
    now = datetime.utcnow()
    schedule = RecurringSchedule(
        weekdays=[0, 1, 2, 3, 4], earliest_departure_time=time(0, 0), latest_departure_time=time(0, 1)
    )
    assert not is_expired(_make_request(schedule), now=now)


def test_expand_schedule_one_off_returns_itself():
    assert expand_schedule(RIDER_1.schedule) == [RIDER_1.schedule]


def test_expand_schedule_recurring_returns_one_instance_per_weekday():
    instances = expand_schedule(RIDER_4.schedule)
    assert len(instances) == len(RIDER_4.schedule.weekdays)
    assert [i.earliest_departure.weekday() for i in instances] == RIDER_4.schedule.weekdays
    # all instances land in the same Monday-Sunday week
    dates = {i.earliest_departure.date() for i in instances}
    assert max(dates) - min(dates) < timedelta(days=7)


def test_expand_schedule_recurring_instances_score_independently():
    recurring = RecurringSchedule(
        weekdays=[0, 1, 2, 3, 4],
        earliest_departure_time=time(9, 0),
        latest_departure_time=time(9, 30),
    )
    instances = expand_schedule(recurring)
    assert len(instances) == 5

    # A narrow one-off window that only overlaps the third (Wednesday) instance.
    wednesday = instances[2].earliest_departure.date()
    narrow_window = OneOffSchedule(
        earliest_departure=datetime.combine(wednesday, time(9, 10)),
        latest_departure=datetime.combine(wednesday, time(9, 20)),
    )
    scores = [temporal_score(instance, narrow_window) for instance in instances]
    assert scores[2] > 0
    assert all(score == 0 for i, score in enumerate(scores) if i != 2)


def test_expand_schedule_recurring_never_lands_on_a_date_before_reference_date():
    # A Thursday reference_date with weekdays=[0] (Monday) is exactly the
    # reproduction that was real, not theoretical: the old week_monday-based
    # expansion put this 3 days *before* reference_date (last Monday), not
    # the upcoming one -- confirmed live, this used to fail.
    thursday = date(2026, 11, 19)
    assert thursday.weekday() == 3
    instances = expand_schedule(
        RecurringSchedule(
            weekdays=[0], earliest_departure_time=time(9, 0), latest_departure_time=time(9, 30)
        ),
        reference_date=thursday,
    )
    assert len(instances) == 1
    assert instances[0].earliest_departure.date() == date(2026, 11, 23)  # the upcoming Monday
    assert instances[0].earliest_departure.date() >= thursday


def test_expand_schedule_recurring_keeps_todays_own_weekday_on_reference_date():
    thursday = date(2026, 11, 19)
    instances = expand_schedule(
        RecurringSchedule(
            weekdays=[3], earliest_departure_time=time(9, 0), latest_departure_time=time(9, 30)
        ),
        reference_date=thursday,
    )
    assert instances[0].earliest_departure.date() == thursday


def test_expand_schedule_recurring_multiple_weekdays_still_span_less_than_a_week():
    # Same invariant test_expand_schedule_recurring_returns_one_instance_per_weekday
    # already checks against the sample dataset -- re-asserted here against
    # the Thursday reference_date above, where the old week-anchored
    # expansion and the new next-occurrence expansion actually disagree on
    # individual dates (just not on this span property).
    thursday = date(2026, 11, 19)
    instances = expand_schedule(
        RecurringSchedule(
            weekdays=[0, 1, 2, 3, 4],
            earliest_departure_time=time(9, 0),
            latest_departure_time=time(9, 30),
        ),
        reference_date=thursday,
    )
    dates = {i.earliest_departure.date() for i in instances}
    assert max(dates) - min(dates) < timedelta(days=7)
    assert min(dates) >= thursday

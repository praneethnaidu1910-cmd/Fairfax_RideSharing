from datetime import datetime, time, timedelta

from app.matching.scoring import (
    capacity_fits,
    compatibility_score,
    directional_score,
    expand_schedule,
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


def test_capacity_fits_hard_constraint():
    assert capacity_fits(RIDER_1, RIDER_7, vehicle_capacity=4)  # 1 + 1 seats
    assert not capacity_fits(RIDER_1, RIDER_7, vehicle_capacity=1)


def test_known_good_pair_scores_higher_than_known_bad_pair():
    good_score = compatibility_score(RIDER_1, RIDER_7, RIDER_1.schedule, RIDER_7.schedule)
    bad_score = compatibility_score(RIDER_1, RIDER_2, RIDER_1.schedule, RIDER_2.schedule)
    assert good_score > bad_score


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

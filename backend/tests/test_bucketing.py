from datetime import datetime, timedelta

from app.matching.bucketing import build_indexes, candidate_groups, candidates_for
from app.sample_data import SAMPLE_REQUESTS
from app.schemas import Location, OneOffSchedule, RideRequest

# rider-1 (Fairfax -> Aldie) and rider-2 (Aldie -> Fairfax): opposite
# commute directions between the same two towns, ~15mi apart -- their
# origin cells (and destination cells) are far apart, not neighbors.
RIDER_1_ID = SAMPLE_REQUESTS[0].id
RIDER_2_ID = SAMPLE_REQUESTS[1].id
# rider-7's origin is ~0.5mi from rider-1's origin, same Aldie destination
# -- close enough to share a pickup, should be a candidate for rider-1.
RIDER_7_ID = SAMPLE_REQUESTS[6].id


def test_far_apart_opposite_direction_pair_excluded():
    groups = candidate_groups(SAMPLE_REQUESTS)
    rider_1_candidates = {r.id for r in groups[RIDER_1_ID]}
    assert RIDER_2_ID not in rider_1_candidates


def test_close_origin_same_destination_pair_included():
    groups = candidate_groups(SAMPLE_REQUESTS)
    rider_1_candidates = {r.id for r in groups[RIDER_1_ID]}
    assert RIDER_7_ID in rider_1_candidates


def test_candidates_for_excludes_self():
    origin_index, destination_index = build_indexes(SAMPLE_REQUESTS)
    request = SAMPLE_REQUESTS[0]
    candidates = candidates_for(request, origin_index, destination_index)
    assert request.id not in {r.id for r in candidates}


def test_far_apart_town_pair_shares_no_bucket():
    now = datetime.utcnow()
    schedule = OneOffSchedule(
        earliest_departure=now,
        latest_departure=now + timedelta(minutes=30),
    )
    fairfax_request = RideRequest(
        rider_id="a",
        origin=Location(lat=38.8462, lng=-77.3064),  # Fairfax
        destination=Location(lat=38.9586, lng=-77.3570),  # Reston
        schedule=schedule,
        contact="555-0200",
    )
    manassas_request = RideRequest(
        rider_id="b",
        origin=Location(lat=38.7509, lng=-77.4753),  # Manassas
        destination=Location(lat=39.0062, lng=-77.4286),  # Sterling
        schedule=schedule,
        contact="555-0201",
    )
    origin_index, destination_index = build_indexes([fairfax_request, manassas_request])
    candidates = candidates_for(fairfax_request, origin_index, destination_index)
    assert manassas_request.id not in {r.id for r in candidates}

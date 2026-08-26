from datetime import datetime, timedelta

from app.matching.engine import DEFAULT_VEHICLE_CAPACITY, MatchingEngine
from app.sample_data import SAMPLE_REQUESTS
from app.schemas import Location, OneOffSchedule, RequestStatus, RideRequest


def _sample_copy() -> list[RideRequest]:
    # match_batch() mutates .status in place -- copy so other test modules
    # importing the shared SAMPLE_REQUESTS list aren't affected.
    return [r.model_copy(deep=True) for r in SAMPLE_REQUESTS]


def test_match_batch_matches_close_same_direction_pair():
    requests = _sample_copy()
    rider_1_id = requests[0].id  # Fairfax -> Aldie
    rider_7_id = requests[6].id  # ~0.5mi from rider-1's origin, same destination

    matches = MatchingEngine().match_batch(requests)

    matched_pairs = [set(m.request_ids) for m in matches]
    assert {rider_1_id, rider_7_id} in matched_pairs


def test_match_batch_updates_status_of_matched_requests_only():
    requests = _sample_copy()
    by_id = {r.id: r for r in requests}

    matches = MatchingEngine().match_batch(requests)

    matched_ids = {rid for m in matches for rid in m.request_ids}
    for request_id, request in by_id.items():
        expected = RequestStatus.MATCHED if request_id in matched_ids else RequestStatus.OPEN
        assert request.status == expected


def test_match_batch_produces_no_capacity_violations():
    requests = _sample_copy()
    by_id = {r.id: r for r in requests}

    matches = MatchingEngine().match_batch(requests)

    for match in matches:
        seats = sum(by_id[rid].seats_needed for rid in match.request_ids)
        assert seats <= DEFAULT_VEHICLE_CAPACITY


def test_match_batch_never_matches_a_large_group_request_alone():
    # rider-10 needs 4 seats -- exactly DEFAULT_VEHICLE_CAPACITY, so it
    # can't fit alongside anyone else's request and should stay unmatched.
    requests = _sample_copy()
    rider_10 = next(r for r in requests if r.seats_needed == 4)

    matches = MatchingEngine().match_batch(requests)

    matched_ids = {rid for m in matches for rid in m.request_ids}
    assert rider_10.id not in matched_ids
    assert rider_10.status == RequestStatus.OPEN


def test_match_batch_excludes_opposite_direction_pair():
    # Two points close enough to share a bucket, but request_b runs the
    # exact reverse of request_a -- docs/MATCHING_ALGORITHM.md's "opposite
    # direction" false-positive. Same time window and seats_needed=1 each,
    # so spatial/temporal/capacity all look perfect; only direction should
    # rule this out.
    now = datetime.utcnow()
    point_p = Location(lat=38.8462, lng=-77.3064)
    point_q = Location(lat=38.8480, lng=-77.3040)
    schedule = OneOffSchedule(earliest_departure=now, latest_departure=now + timedelta(minutes=30))

    request_a = RideRequest(
        rider_id="a", origin=point_p, destination=point_q, schedule=schedule, contact="555-0300"
    )
    request_b = RideRequest(
        rider_id="b", origin=point_q, destination=point_p, schedule=schedule, contact="555-0301"
    )

    matches = MatchingEngine().match_batch([request_a, request_b])

    assert matches == []
    assert request_a.status == RequestStatus.OPEN
    assert request_b.status == RequestStatus.OPEN

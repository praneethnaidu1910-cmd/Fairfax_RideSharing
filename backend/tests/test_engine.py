import asyncio
import contextlib
from datetime import datetime, timedelta

import pytest

from app.matching import engine as engine_module
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


def test_match_batch_skips_an_expired_open_request():
    # rider-1/rider-7 are the known-good pair (test_match_batch_matches_
    # close_same_direction_pair above); backdating rider-1's window into
    # the past should pull it out of matching entirely (TASKS.md #14)
    # rather than letting it win the slot a still-live request could use.
    requests = _sample_copy()
    rider_1 = requests[0]
    rider_7_id = requests[6].id
    now = datetime.utcnow()
    rider_1.schedule = OneOffSchedule(
        earliest_departure=now - timedelta(hours=2), latest_departure=now - timedelta(hours=1)
    )

    matches = MatchingEngine().match_batch(requests)

    matched_ids = {rid for m in matches for rid in m.request_ids}
    assert rider_1.id not in matched_ids
    assert rider_7_id not in matched_ids
    assert rider_1.status == RequestStatus.OPEN  # never flipped, just excluded


def test_on_new_request_does_not_match_or_pool_an_expired_incoming_request():
    engine = MatchingEngine()
    by_rider = {r.rider_id: r for r in _sample_copy()}
    rider_1 = by_rider["rider-1"]
    now = datetime.utcnow()
    rider_1.schedule = OneOffSchedule(
        earliest_departure=now - timedelta(hours=2), latest_departure=now - timedelta(hours=1)
    )

    matches = engine.on_new_request(rider_1)

    assert matches == []
    assert rider_1 not in engine._unmatched


def test_on_new_request_skips_a_candidate_that_expired_while_pooled():
    engine = MatchingEngine()
    by_rider = {r.rider_id: r for r in _sample_copy()}
    rider_1 = by_rider["rider-1"]
    now = datetime.utcnow()
    rider_1.schedule = OneOffSchedule(
        earliest_departure=now - timedelta(hours=2), latest_departure=now - timedelta(hours=1)
    )
    engine._unmatched.append(rider_1)

    matches = engine.on_new_request(by_rider["rider-7"])

    assert matches == []
    assert by_rider["rider-7"] in engine._unmatched
    assert rider_1.status == RequestStatus.OPEN


def test_on_new_request_matches_close_pair_scoring_only_bucketed_candidates(monkeypatch):
    # Seed a pool of several requests, most nowhere near rider-7's corridor
    # -- bucketing should keep on_new_request from scoring against most of
    # them, which this asserts on the compatibility_score call count, not
    # just the match outcome (TASKS.md #5's own acceptance wording).
    engine = MatchingEngine()
    by_rider = {r.rider_id: r for r in _sample_copy()}
    for rider_id in ("rider-1", "rider-3", "rider-4", "rider-6", "rider-9"):
        engine._unmatched.append(by_rider[rider_id])

    call_count = 0
    original_score = engine_module.compatibility_score

    def counting_score(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return original_score(*args, **kwargs)

    monkeypatch.setattr(engine_module, "compatibility_score", counting_score)

    matches = engine.on_new_request(by_rider["rider-7"])

    assert len(matches) == 1
    assert set(matches[0].request_ids) == {by_rider["rider-7"].id, by_rider["rider-1"].id}
    # Only rider-1 shares rider-7's H3 neighborhood on both ends: scoring
    # ran once, not once per request in the 5-request pool.
    assert call_count == 1
    assert by_rider["rider-1"] not in engine._unmatched
    assert len(engine._unmatched) == 4


def test_on_new_request_joins_pool_when_no_candidate_matches():
    engine = MatchingEngine()
    by_rider = {r.rider_id: r for r in _sample_copy()}

    matches = engine.on_new_request(by_rider["rider-6"])  # Manassas -> Sterling, alone

    assert matches == []
    assert by_rider["rider-6"] in engine._unmatched
    assert by_rider["rider-6"].status == RequestStatus.OPEN


def test_on_new_request_matches_across_two_sequential_arrivals():
    # Requests trickling in one at a time (docs/MATCHING_ALGORITHM.md's
    # real-time model): the first has nothing to match yet, the second
    # closes the loop.
    engine = MatchingEngine()
    by_rider = {r.rider_id: r for r in _sample_copy()}

    first_matches = engine.on_new_request(by_rider["rider-1"])
    assert first_matches == []
    assert by_rider["rider-1"].status == RequestStatus.OPEN

    second_matches = engine.on_new_request(by_rider["rider-7"])
    assert len(second_matches) == 1
    assert set(second_matches[0].request_ids) == {by_rider["rider-1"].id, by_rider["rider-7"].id}
    assert by_rider["rider-1"].status == RequestStatus.MATCHED
    assert by_rider["rider-7"].status == RequestStatus.MATCHED
    assert engine._unmatched == []


@pytest.mark.asyncio
async def test_run_forever_publishes_match_for_two_submitted_requests():
    # The asyncio.Queue-backed pipeline: submit() feeds `incoming`,
    # run_forever() drains it via on_new_request() and publishes matches
    # to `matches` -- the consumer side TASKS.md #6 wires a WebSocket to.
    engine = MatchingEngine()
    by_rider = {r.rider_id: r for r in _sample_copy()}

    worker = asyncio.create_task(engine.run_forever())
    await engine.submit(by_rider["rider-1"])
    await engine.submit(by_rider["rider-7"])
    await engine.incoming.join()

    worker.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await worker

    assert engine.matches.qsize() == 1
    match = engine.matches.get_nowait()
    assert set(match.request_ids) == {by_rider["rider-1"].id, by_rider["rider-7"].id}


@pytest.mark.asyncio
async def test_run_forever_broadcasts_match_to_every_subscriber():
    # TASKS.md #12 needs two simultaneous WebSocket connections (two
    # browser tabs) to both see the same match -- subscribe() is what
    # makes that a real broadcast instead of the two connections splitting
    # a single shared queue competing-consumer style.
    engine = MatchingEngine()
    by_rider = {r.rider_id: r for r in _sample_copy()}

    subscriber_a = engine.subscribe()
    subscriber_b = engine.subscribe()

    worker = asyncio.create_task(engine.run_forever())
    await engine.submit(by_rider["rider-1"])
    await engine.submit(by_rider["rider-7"])
    await engine.incoming.join()

    worker.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await worker

    match_a = subscriber_a.get_nowait()
    match_b = subscriber_b.get_nowait()
    assert set(match_a.request_ids) == {by_rider["rider-1"].id, by_rider["rider-7"].id}
    assert set(match_b.request_ids) == {by_rider["rider-1"].id, by_rider["rider-7"].id}
    # The pre-existing single-subscriber queue still gets it too -- nothing
    # about adding subscribe() should regress it.
    assert engine.matches.qsize() == 1

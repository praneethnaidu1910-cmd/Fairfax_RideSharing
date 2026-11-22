import asyncio
import contextlib
import threading
from datetime import date, datetime, time, timedelta

import pytest

from app.db import make_session_factory
from app.matching import engine as engine_module
from app.matching import scoring as scoring_module
from app.matching.engine import DEFAULT_VEHICLE_CAPACITY, MatchingEngine
from app.sample_data import SAMPLE_REQUESTS
from app.schemas import Location, OneOffSchedule, RecurringSchedule, RequestStatus, RideRequest
from app.store import RequestStore


class _FixedDate(date):
    """A real Thursday, pinned so
    test_on_new_request_matches_a_recurring_rider_against_next_weeks_one_off_occurrence
    doesn't depend on which real day the suite happens to run on."""

    @classmethod
    def today(cls) -> date:
        return cls(2026, 11, 19)


def _sample_copy() -> list[RideRequest]:
    # match_batch() mutates .status in place -- copy so other test modules
    # importing the shared SAMPLE_REQUESTS list aren't affected.
    return [r.model_copy(deep=True) for r in SAMPLE_REQUESTS]


def _store_backed_request(rider_id: str, lat: float, lng: float) -> RideRequest:
    earliest = datetime.utcnow() + timedelta(hours=1)
    return RideRequest(
        rider_id=rider_id,
        origin=Location(lat=lat, lng=lng),
        destination=Location(lat=38.9757, lng=-77.6122),
        schedule=OneOffSchedule(
            earliest_departure=earliest,
            latest_departure=earliest + timedelta(minutes=30),
        ),
        seats_needed=1,
        contact="555-0199",
    )


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


def test_match_batch_match_reason_is_real_not_a_canned_string():
    # SCOPE.md MVP item 6: the engine has to actually state why a given
    # pair matched, not print the same sentence for every match.
    requests = _sample_copy()
    rider_1_id = requests[0].id
    rider_7_id = requests[6].id

    matches = MatchingEngine().match_batch(requests)

    match = next(m for m in matches if set(m.request_ids) == {rider_1_id, rider_7_id})
    assert "mi apart" in match.reason
    assert "min window overlap" in match.reason
    assert "capacity fits" in match.reason


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


def test_on_new_request_matches_a_precise_departure_time_inside_the_others_window():
    # scoring.temporal_score()'s own fix: a rider who posts a precise
    # departure "window" (latest == earliest -- OneOffSchedule's validator
    # allows this, e.g. typing the same value into both fields instead of
    # giving themselves flexibility) used to be unmatchable with *anyone*,
    # even an identical-route rider whose real window fully contains that
    # exact instant, because the old overlap math scored that pair's
    # temporal fit as 0.0 -- indistinguishable from two riders hours apart
    # -- and MIN_TEMPORAL_SCORE's hard cutoff then rejected it outright.
    # Confirmed this was real against the live engine before the fix: two
    # arrivals, same origin/destination, came back unmatched, both sitting
    # in the pool forever.
    point = Location(lat=38.8462, lng=-77.3064)
    destination = Location(lat=38.9757, lng=-77.6122)
    now = datetime.utcnow() + timedelta(hours=2)

    precise_rider = RideRequest(
        rider_id="precise",
        origin=point,
        destination=destination,
        schedule=OneOffSchedule(earliest_departure=now, latest_departure=now),
        contact="555-0320",
    )
    flexible_rider = RideRequest(
        rider_id="flexible",
        origin=point,
        destination=destination,
        schedule=OneOffSchedule(
            earliest_departure=now - timedelta(minutes=15),
            latest_departure=now + timedelta(minutes=15),
        ),
        contact="555-0321",
    )

    engine = MatchingEngine()
    assert engine.on_new_request(precise_rider) == []
    matches = engine.on_new_request(flexible_rider)

    assert len(matches) == 1
    assert set(matches[0].request_ids) == {precise_rider.id, flexible_rider.id}
    assert precise_rider.status == RequestStatus.MATCHED
    assert flexible_rider.status == RequestStatus.MATCHED


def test_match_batch_excludes_pair_with_no_window_overlap():
    # Same corridor, same direction, close origins -- spatial and
    # directional scores both look great -- but the two departure windows
    # are 13 hours apart on the same day, with zero overlap. Confirmed this
    # was real, not theoretical, before adding MIN_TEMPORAL_SCORE:
    # WEIGHT_SPATIAL + WEIGHT_DIRECTIONAL (0.75) alone was enough to win a
    # greedy match slot even with temporal_score() == 0.0, and the match's
    # own `reason` string literally read "0min window overlap" -- the same
    # kind of false positive MIN_DIRECTIONAL_SCORE already exists to catch
    # for direction, just never closed for time.
    point_p = Location(lat=38.8462, lng=-77.3064)
    point_q = Location(lat=38.8500, lng=-77.3100)
    destination = Location(lat=38.9757, lng=-77.6122)
    morning = OneOffSchedule(
        earliest_departure=datetime(2026, 12, 1, 7, 0),
        latest_departure=datetime(2026, 12, 1, 7, 30),
    )
    evening = OneOffSchedule(
        earliest_departure=datetime(2026, 12, 1, 20, 0),
        latest_departure=datetime(2026, 12, 1, 20, 30),
    )

    request_a = RideRequest(
        rider_id="a", origin=point_p, destination=destination, schedule=morning, contact="555-0310"
    )
    request_b = RideRequest(
        rider_id="b", origin=point_q, destination=destination, schedule=evening, contact="555-0311"
    )

    matches = MatchingEngine().match_batch([request_a, request_b])

    assert matches == []
    assert request_a.status == RequestStatus.OPEN
    assert request_b.status == RequestStatus.OPEN


def test_on_new_request_does_not_match_a_candidate_with_no_window_overlap():
    # Incremental counterpart of the match_batch test above -- same
    # disjoint-window fixture, arriving one at a time the way real traffic
    # does, through on_new_request() instead of a single match_batch() call.
    engine = MatchingEngine()
    point_p = Location(lat=38.8462, lng=-77.3064)
    point_q = Location(lat=38.8500, lng=-77.3100)
    destination = Location(lat=38.9757, lng=-77.6122)
    morning = OneOffSchedule(
        earliest_departure=datetime(2026, 12, 1, 7, 0),
        latest_departure=datetime(2026, 12, 1, 7, 30),
    )
    evening = OneOffSchedule(
        earliest_departure=datetime(2026, 12, 1, 20, 0),
        latest_departure=datetime(2026, 12, 1, 20, 30),
    )
    request_a = RideRequest(
        rider_id="a", origin=point_p, destination=destination, schedule=morning, contact="555-0312"
    )
    request_b = RideRequest(
        rider_id="b", origin=point_q, destination=destination, schedule=evening, contact="555-0313"
    )

    first_matches = engine.on_new_request(request_a)
    second_matches = engine.on_new_request(request_b)

    assert first_matches == []
    assert second_matches == []
    assert request_a.status == RequestStatus.OPEN
    assert request_b.status == RequestStatus.OPEN
    assert request_b in engine._unmatched


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


def test_on_new_request_purges_an_expired_pool_member_instead_of_leaving_it_forever():
    # test_on_new_request_skips_a_candidate_that_expired_while_pooled just
    # above proves an expired pool member never wins a match -- this proves
    # the other half, which that test never checked: it doesn't just lose
    # every future scoring round, it actually leaves the pool, instead of
    # sitting in self._unmatched for the rest of the process's life. Before
    # this fix, nothing anywhere ever pruned self._unmatched -- every
    # one-off request a real user posts and never matches (routine, not
    # rare, for SCOPE.md's actual ~1,000-person deployment) stayed there,
    # unbounded, for as long as the process ran, making both the pool
    # itself and the bucketing index rebuilt from it on every single call
    # grow forever. Confirmed real, not theoretical, with a live script
    # before writing this fix: pooled a request whose window was a second
    # from passing, let real wall-clock time carry it past that window,
    # then ran an unrelated request through on_new_request() -- the expired
    # request was still sitting in self._unmatched afterward.
    engine = MatchingEngine()
    by_rider = {r.rider_id: r for r in _sample_copy()}
    rider_1 = by_rider["rider-1"]
    now = datetime.utcnow()
    rider_1.schedule = OneOffSchedule(
        earliest_departure=now - timedelta(hours=2), latest_departure=now - timedelta(hours=1)
    )
    engine._unmatched.append(rider_1)

    # rider-9 (Falls Church -> Centerville) shares no corridor with rider-1
    # (Fairfax -> Aldie) -- any unrelated arrival is enough to trigger the
    # sweep, it doesn't need to be a real candidate for rider-1 at all.
    engine.on_new_request(by_rider["rider-9"])

    assert rider_1 not in engine._unmatched


def _full_car_recurring_request(rider_id: str, seats_needed: int) -> RideRequest:
    # SCOPE.md's "a friend posting on behalf of a couple of others," taken
    # to the vehicle's own limit -- a real, valid trip, not a malformed
    # fixture. Recurring, not one-off, is the point: a RecurringSchedule
    # never expires (scoring.is_expired() always returns False for one), so
    # nothing's window-based ever removes it from the pool the way task 44's
    # expiry prune does for a one-off.
    return RideRequest(
        rider_id=rider_id,
        origin=Location(lat=38.8462, lng=-77.3064),
        destination=Location(lat=38.9586, lng=-77.3570),
        schedule=RecurringSchedule(
            weekdays=[0, 1, 2, 3, 4],
            earliest_departure_time=time(9, 0),
            latest_departure_time=time(9, 30),
        ),
        seats_needed=seats_needed,
        contact="555-0400",
    )


def test_on_new_request_does_not_pool_a_request_no_partner_could_ever_fit():
    # capacity_fits() needs a.seats_needed + b.seats_needed <=
    # vehicle_capacity, and the smallest possible b.seats_needed is 1
    # (Field(ge=1)) -- so a request whose own seats_needed already equals
    # DEFAULT_VEHICLE_CAPACITY can never satisfy that for *any* partner, no
    # matter how compatible one would otherwise be. Confirmed real, not
    # theoretical, with a live script before this fix: on_new_request()
    # pooled exactly this request on arrival (no check at all for "could
    # this ever match anyone"), then ran 50 unrelated, mutually-compatible
    # requests through the same engine one at a time -- every one of those
    # 50 paired off and left the pool normally, but this one was still
    # sitting in self._unmatched afterward, with nothing anywhere having
    # ever touched it, and nothing ever would: a RecurringSchedule never
    # expires, so task 44's own expiry prune doesn't reach it either.
    engine = MatchingEngine()
    full_car = _full_car_recurring_request("rider-full-car", DEFAULT_VEHICLE_CAPACITY)

    matches = engine.on_new_request(full_car)

    assert matches == []
    assert full_car not in engine._unmatched
    assert full_car.status == RequestStatus.OPEN  # still a real, open, visible request


def test_on_new_request_purges_a_capacity_impossible_pool_member_instead_of_leaving_it_forever():
    # The other half of the fix above, same shape as
    # test_on_new_request_purges_an_expired_pool_member_instead_of_leaving_it_forever:
    # a member that's already sitting in the pool (e.g. one pooled before
    # this fix existed) gets swept out by the same prune that now runs at
    # the top of every incremental call, not just kept out of the pool on
    # its own way in.
    engine = MatchingEngine()
    full_car = _full_car_recurring_request("rider-full-car-already-pooled", DEFAULT_VEHICLE_CAPACITY)
    engine._unmatched.append(full_car)

    by_rider = {r.rider_id: r for r in _sample_copy()}
    # Any unrelated arrival is enough to trigger the sweep -- it doesn't
    # need to be a real candidate for full_car at all.
    engine.on_new_request(by_rider["rider-9"])

    assert full_car not in engine._unmatched


def test_remove_from_pool_drops_a_pooled_request_by_id():
    engine = MatchingEngine()
    by_rider = {r.rider_id: r for r in _sample_copy()}
    engine._unmatched.append(by_rider["rider-1"])

    engine.remove_from_pool(by_rider["rider-1"].id)

    assert engine._unmatched == []


def test_remove_from_pool_is_a_noop_for_an_id_never_pooled():
    engine = MatchingEngine()
    by_rider = {r.rider_id: r for r in _sample_copy()}
    engine._unmatched.append(by_rider["rider-1"])

    engine.remove_from_pool(by_rider["rider-7"].id)  # never pooled

    assert engine._unmatched == [by_rider["rider-1"]]


def test_a_cancelled_pooled_request_cannot_win_a_later_match_slot():
    # TASKS.md #15's own acceptance wording: prove a cancelled request
    # can't win a match slot. remove_from_pool() is what POST
    # /requests/{id}/cancel calls -- rider-1 sitting in the pool,
    # "cancelled" (removed), then rider-7 arrives and would have matched
    # rider-1 (the known-good pair) but now has nothing to match.
    engine = MatchingEngine()
    by_rider = {r.rider_id: r for r in _sample_copy()}
    engine._unmatched.append(by_rider["rider-1"])

    engine.remove_from_pool(by_rider["rider-1"].id)
    matches = engine.on_new_request(by_rider["rider-7"])

    assert matches == []
    assert by_rider["rider-7"] in engine._unmatched
    assert by_rider["rider-1"].status == RequestStatus.OPEN  # never touched by remove_from_pool


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


def test_on_new_request_matches_a_recurring_rider_against_next_weeks_one_off_occurrence(
    monkeypatch,
):
    # app/matching/scoring.py's expand_schedule() used to anchor every
    # weekday to the Monday-Sunday week *containing* "today," not that
    # weekday's next real occurrence -- silently landing on a date in the
    # past for any weekday earlier in the week than today. Confirmed real,
    # not theoretical, with a live script before that fix: from a real
    # Thursday, a recurring rider posting "every Monday, 9:00-9:30" and a
    # one-off rider posting the very next Monday, 9:05-9:20 -- same
    # origin/destination, a textbook match on every other dimension --
    # never matched, because the recurring side expanded to the Monday 3
    # days *before* reference_date while the one-off side had the real
    # upcoming Monday, so temporal_score() saw two different calendar dates
    # and scored 0.0 overlap. Pin "today" to that same Thursday here so
    # this doesn't depend on which real day the suite happens to run on.
    monkeypatch.setattr(scoring_module, "date", _FixedDate)

    origin = Location(lat=38.8462, lng=-77.3064)
    destination = Location(lat=38.9757, lng=-77.6122)
    recurring_rider = RideRequest(
        rider_id="recurring-commuter",
        origin=origin,
        destination=destination,
        schedule=RecurringSchedule(
            weekdays=[0], earliest_departure_time=time(9, 0), latest_departure_time=time(9, 30)
        ),
        contact="555-0301",
    )
    upcoming_monday = _FixedDate.today() + timedelta(
        days=(0 - _FixedDate.today().weekday()) % 7
    )
    one_off_rider = RideRequest(
        rider_id="one-off-rider",
        origin=origin,
        destination=destination,
        schedule=OneOffSchedule(
            earliest_departure=datetime.combine(upcoming_monday, time(9, 5)),
            latest_departure=datetime.combine(upcoming_monday, time(9, 20)),
        ),
        contact="555-0302",
    )

    engine = MatchingEngine()
    assert engine.on_new_request(recurring_rider) == []
    matches = engine.on_new_request(one_off_rider)

    assert len(matches) == 1
    assert set(matches[0].request_ids) == {recurring_rider.id, one_off_rider.id}
    assert recurring_rider.status == RequestStatus.MATCHED
    assert one_off_rider.status == RequestStatus.MATCHED


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


@pytest.mark.asyncio
async def test_run_forever_survives_on_new_request_raising(monkeypatch):
    # Confirmed this was real, not theoretical, before the fix: without a
    # try/except around on_new_request() inside the loop, an exception
    # (e.g. a transient DB error from store.save()) propagated out of
    # run_forever() and ended the background task for good -- every
    # request submitted after the failing one just sat in `incoming`
    # forever, never matched, with nothing telling a caller the pipeline
    # had died. This proves the opposite: one request's on_new_request()
    # raising doesn't stop the next, unrelated request from matching
    # normally on the same still-running worker.
    engine = MatchingEngine()
    by_rider = {r.rider_id: r for r in _sample_copy()}

    original_on_new_request = engine.on_new_request
    calls = {"n": 0}

    def flaky_on_new_request(request):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("simulated transient failure")
        return original_on_new_request(request)

    monkeypatch.setattr(engine, "on_new_request", flaky_on_new_request)

    worker = asyncio.create_task(engine.run_forever())
    await engine.submit(by_rider["rider-6"])  # calls[1] -- raises, dropped
    await engine.submit(by_rider["rider-1"])  # calls[2] -- real matching resumes
    await engine.submit(by_rider["rider-7"])  # calls[3] -- matches rider-1
    await engine.incoming.join()

    assert not worker.done(), "run_forever() must not die from one bad request"
    worker.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await worker

    assert engine.matches.qsize() == 1
    match = engine.matches.get_nowait()
    assert set(match.request_ids) == {by_rider["rider-1"].id, by_rider["rider-7"].id}


def test_on_new_request_does_not_revert_a_cancel_of_its_own_best_candidate(monkeypatch):
    # A different race than test_run_forever_does_not_match_a_request_
    # cancelled_while_still_queued above: that one covers a request still
    # sitting in `incoming`. This one covers a request already sitting in
    # self._unmatched (pooled, scoreable) that gets cancelled *while*
    # on_new_request() is in the middle of scoring it as the best
    # candidate for a brand-new incoming request -- POST
    # /requests/{id}/cancel's cancel_request() (app/router.py) is a sync
    # FastAPI route, which Starlette dispatches to a threadpool worker, not
    # the event loop this engine's on_new_request() runs on, so the two
    # really can overlap. Forces that exact interleaving deterministically
    # by pausing on_new_request() mid-scoring (via a monkeypatched
    # compatibility_score, called while best_candidate is still being
    # decided), running the real cancel sequence against the pool's only
    # candidate from another thread, then letting on_new_request() resume
    # into its post-scoring recheck.
    session_factory = make_session_factory()
    store = RequestStore(session_factory)
    engine = MatchingEngine(store=store)

    candidate = _store_backed_request("rider-pool-race-candidate", 38.8462, -77.3064)
    incoming = _store_backed_request("rider-pool-race-incoming", 38.8500, -77.3100)
    store.add(candidate)
    store.add(incoming)
    engine._unmatched.append(candidate)

    reached = threading.Event()
    release = threading.Event()
    real_score = engine_module.compatibility_score

    def pausing_score(*args, **kwargs):
        if not reached.is_set():
            reached.set()
            release.wait(timeout=5)
        return real_score(*args, **kwargs)

    monkeypatch.setattr(engine_module, "compatibility_score", pausing_score)

    result: dict = {}

    def run_on_new_request():
        try:
            result["matches"] = engine.on_new_request(incoming)
        except Exception as exc:  # pragma: no cover -- only hit pre-fix
            result["exception"] = exc

    worker = threading.Thread(target=run_on_new_request)
    worker.start()
    assert reached.wait(timeout=5), "on_new_request never reached scoring"

    # Mirrors router.py's cancel_request() exactly, run concurrently from
    # what's really a separate thread in production: a fresh copy flips to
    # CANCELLED and saves, then drops out of the pool.
    fresh_candidate = store.get(candidate.id)
    fresh_candidate.status = RequestStatus.CANCELLED
    fresh_candidate.status_changed_at = datetime.utcnow()
    store.save(fresh_candidate)
    engine.remove_from_pool(candidate.id)

    release.set()
    worker.join(timeout=5)

    assert "exception" not in result, f"on_new_request raised: {result.get('exception')!r}"
    assert result["matches"] == []
    assert store.get(candidate.id).status == RequestStatus.CANCELLED
    assert store.get(candidate.id).matched_with is None
    assert store.get(incoming.id).status == RequestStatus.OPEN
    assert incoming in engine._unmatched
    assert candidate not in engine._unmatched


def test_on_new_request_does_not_revert_a_cancel_of_the_incoming_request_itself(monkeypatch):
    # The third leg of the same triangle: test_run_forever_does_not_match_
    # a_request_cancelled_while_still_queued covers a request still sitting
    # in `incoming`, and test_on_new_request_does_not_revert_a_cancel_of_
    # its_own_best_candidate (just above) covers an already-pooled
    # candidate getting cancelled mid-scoring. This covers the remaining
    # gap: the *incoming* request itself -- not yet pooled, so
    # remove_from_pool() can't reach it either -- getting cancelled by its
    # own poster during that same scoring window, before on_new_request()
    # commits a match. Same interleaving trick as the test above, just
    # cancelling `incoming` instead of `candidate` once scoring is paused.
    session_factory = make_session_factory()
    store = RequestStore(session_factory)
    engine = MatchingEngine(store=store)

    candidate = _store_backed_request("rider-incoming-race-candidate", 38.8462, -77.3064)
    incoming = _store_backed_request("rider-incoming-race-incoming", 38.8500, -77.3100)
    store.add(candidate)
    store.add(incoming)
    engine._unmatched.append(candidate)

    reached = threading.Event()
    release = threading.Event()
    real_score = engine_module.compatibility_score

    def pausing_score(*args, **kwargs):
        if not reached.is_set():
            reached.set()
            release.wait(timeout=5)
        return real_score(*args, **kwargs)

    monkeypatch.setattr(engine_module, "compatibility_score", pausing_score)

    result: dict = {}

    def run_on_new_request():
        try:
            result["matches"] = engine.on_new_request(incoming)
        except Exception as exc:  # pragma: no cover -- only hit pre-fix
            result["exception"] = exc

    worker = threading.Thread(target=run_on_new_request)
    worker.start()
    assert reached.wait(timeout=5), "on_new_request never reached scoring"

    # Mirrors router.py's cancel_request() exactly, but against the
    # incoming request itself -- it isn't pooled yet, so
    # remove_from_pool() is a no-op here, same as the real race.
    fresh_incoming = store.get(incoming.id)
    fresh_incoming.status = RequestStatus.CANCELLED
    fresh_incoming.status_changed_at = datetime.utcnow()
    store.save(fresh_incoming)
    engine.remove_from_pool(incoming.id)

    release.set()
    worker.join(timeout=5)

    assert "exception" not in result, f"on_new_request raised: {result.get('exception')!r}"
    assert result["matches"] == []
    assert store.get(incoming.id).status == RequestStatus.CANCELLED
    assert store.get(incoming.id).matched_with is None
    assert store.get(candidate.id).status == RequestStatus.OPEN
    assert store.get(candidate.id).matched_with is None
    assert candidate in engine._unmatched
    assert incoming not in engine._unmatched


def test_on_new_request_does_not_revert_a_cancel_that_lands_right_before_its_own_write(
    monkeypatch,
):
    # The sliver the two race tests just above don't reach: both of them
    # cancel *during scoring*, which the post-scoring rechecks (the ones
    # those two tests exist to prove) catch cleanly. This one cancels
    # *after* the second recheck has already passed -- both sides still
    # OPEN -- but before the matched_at write that follows it actually
    # lands. "Recheck right before writing" is still a separate read
    # followed by a separate write, so there's always some nonzero gap
    # between them, exactly the same shape save_if_open() closed for
    # cancel_request() (task 51) -- just on the engine's own match-commit
    # side this time, which used two separate save() calls with the same
    # gap neither recheck above can close. Pauses right after
    # on_new_request()'s own matched_at := datetime.utcnow() call (its
    # first action once both rechecks have passed) via a monkeypatched
    # datetime, runs the real cancel_request() sequence against the pooled
    # candidate from another thread in that exact gap, then lets
    # on_new_request() resume into its write.
    session_factory = make_session_factory()
    store = RequestStore(session_factory)
    engine = MatchingEngine(store=store)

    candidate = _store_backed_request("rider-write-race-candidate", 38.8462, -77.3064)
    incoming = _store_backed_request("rider-write-race-incoming", 38.8500, -77.3100)
    store.add(candidate)
    store.add(incoming)
    engine._unmatched.append(candidate)

    reached = threading.Event()
    release = threading.Event()
    real_datetime = engine_module.datetime

    class PausingDatetime(real_datetime):
        _fired = False

        @classmethod
        def utcnow(cls):
            if not cls._fired:
                cls._fired = True
                reached.set()
                release.wait(timeout=5)
            return real_datetime.utcnow()

    monkeypatch.setattr(engine_module, "datetime", PausingDatetime)

    result: dict = {}

    def run_on_new_request():
        try:
            result["matches"] = engine.on_new_request(incoming)
        except Exception as exc:  # pragma: no cover -- only hit pre-fix
            result["exception"] = exc

    worker = threading.Thread(target=run_on_new_request)
    worker.start()
    assert reached.wait(timeout=5), "on_new_request never reached its own write"

    # Mirrors router.py's cancel_request() exactly, run concurrently from
    # what's really a separate thread in production, landing in the gap
    # between on_new_request()'s matched_at timestamp and its actual write.
    fresh_candidate = store.get(candidate.id)
    fresh_candidate.status = RequestStatus.CANCELLED
    fresh_candidate.status_changed_at = datetime.utcnow()
    assert store.save_if_open(fresh_candidate) is True
    engine.remove_from_pool(candidate.id)

    release.set()
    worker.join(timeout=5)

    assert "exception" not in result, f"on_new_request raised: {result.get('exception')!r}"
    assert result["matches"] == []
    assert store.get(candidate.id).status == RequestStatus.CANCELLED
    assert store.get(candidate.id).matched_with is None
    assert store.get(incoming.id).status == RequestStatus.OPEN
    assert store.get(incoming.id).matched_with is None
    assert candidate not in engine._unmatched
    assert incoming in engine._unmatched


@pytest.mark.asyncio
async def test_run_forever_does_not_match_a_request_cancelled_while_still_queued():
    # TASKS.md #15's acceptance criterion is "a cancelled request can't
    # win a later match" -- test_a_cancelled_pooled_request_cannot_win_a_
    # later_match_slot above covers that for a request already sitting in
    # self._unmatched, which is all remove_from_pool() (called by
    # router.py's cancel_request()) can reach. This covers the gap right
    # next to it: a request can also be cancelled while it's still
    # sitting in `incoming`, queued by submit() but not yet drained by
    # this loop -- remove_from_pool() is a no-op for it (it was never
    # pooled), and the object sitting in `incoming` is a different Python
    # instance than the fresh one store.get()/cancel_request() mutated, so
    # its in-memory .status is still OPEN. Confirmed this was real, not
    # theoretical, before the fix in run_forever() that re-checks the
    # store: without it, this test's rider-a came back MATCHED, with its
    # CANCELLED status silently overwritten.
    session_factory = make_session_factory()
    store = RequestStore(session_factory)
    engine = MatchingEngine(store=store)

    rider_a = _store_backed_request("rider-cancel-race-a", 38.8462, -77.3064)
    rider_b = _store_backed_request("rider-cancel-race-b", 38.8500, -77.3100)
    store.add(rider_a)
    store.add(rider_b)

    worker = asyncio.create_task(engine.run_forever())
    try:
        await engine.submit(rider_a)

        # Mirrors router.py's cancel_request(): a fresh copy, not the
        # object just submitted, gets flipped to CANCELLED and saved,
        # then dropped from the pool (a no-op -- it isn't pooled yet).
        fresh_a = store.get(rider_a.id)
        fresh_a.status = RequestStatus.CANCELLED
        fresh_a.status_changed_at = datetime.utcnow()
        store.save(fresh_a)
        engine.remove_from_pool(rider_a.id)

        await engine.submit(rider_b)
        await engine.incoming.join()
    finally:
        worker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker

    assert store.get(rider_a.id).status == RequestStatus.CANCELLED
    assert store.get(rider_a.id).matched_with is None
    assert store.get(rider_b.id).status == RequestStatus.OPEN

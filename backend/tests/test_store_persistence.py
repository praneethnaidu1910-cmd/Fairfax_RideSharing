"""TASKS.md #9's own acceptance test: a request posted through one store
is still there through a second, independent store/session pointed at the
same database -- simulating a server restart without actually restarting
a process.
"""

from datetime import datetime, timedelta

from app.db import make_session_factory
from app.schemas import Location, OneOffSchedule, RequestStatus, RideRequest
from app.store import RequestStore


def _sample_request(rider_id: str) -> RideRequest:
    earliest = datetime.utcnow() + timedelta(hours=1)
    return RideRequest(
        rider_id=rider_id,
        origin=Location(lat=38.8462, lng=-77.3064),
        destination=Location(lat=38.9757, lng=-77.6122),
        schedule=OneOffSchedule(
            earliest_departure=earliest,
            latest_departure=earliest + timedelta(minutes=30),
        ),
        seats_needed=1,
        contact="555-0199",
    )


def test_request_survives_a_simulated_restart():
    request = _sample_request("rider-restart-test")

    store = RequestStore(make_session_factory())
    store.add(request)

    # A brand-new store backed by a brand-new session factory (its own
    # Engine, its own connection pool) -- nothing here shares a Python
    # object with `store` above. If the request comes back, it's because
    # Postgres persisted it, not because of an in-memory reference.
    restarted_store = RequestStore(make_session_factory())
    fetched = restarted_store.get(request.id)

    assert fetched is not None
    assert fetched.id == request.id
    assert fetched.rider_id == "rider-restart-test"
    assert fetched.contact == "555-0199"
    assert fetched.origin.lat == request.origin.lat
    assert fetched.origin.lng == request.origin.lng
    assert fetched.status.value == "open"


def test_list_open_reflects_rows_written_by_a_different_store_instance():
    request = _sample_request("rider-restart-list-test")
    RequestStore(make_session_factory()).add(request)

    open_ids = {r.id for r in RequestStore(make_session_factory()).list_open()}
    assert request.id in open_ids


def test_save_persists_a_status_change_across_a_simulated_restart():
    request = _sample_request("rider-restart-save-test")
    other = _sample_request("rider-restart-save-test-2")

    store = RequestStore(make_session_factory())
    store.add(request)
    store.add(other)

    request.status = RequestStatus.MATCHED
    request.matched_with = other.id
    store.save(request)

    restarted_store = RequestStore(make_session_factory())
    fetched = restarted_store.get(request.id)
    assert fetched is not None
    assert fetched.status.value == "matched"
    assert fetched.matched_with == other.id


def test_save_if_open_writes_and_returns_true_when_the_stored_row_is_still_open():
    request = _sample_request("rider-save-if-open-true")
    other = _sample_request("rider-save-if-open-true-2")
    store = RequestStore(make_session_factory())
    store.add(request)
    store.add(other)

    request.status = RequestStatus.CANCELLED
    request.matched_with = None
    request.status_changed_at = datetime.utcnow()
    assert store.save_if_open(request) is True

    fetched = store.get(request.id)
    assert fetched.status == RequestStatus.CANCELLED


def test_save_if_open_does_not_write_and_returns_false_when_the_stored_row_is_not_open():
    # The exact TOCTOU gap this method exists to close: `request` here is a
    # stale in-memory read (still showing OPEN) of a row some other writer
    # already flipped away from OPEN in the store. A blind save() would
    # overwrite that -- save_if_open()'s own WHERE clause is what has to
    # catch it instead, in one atomic statement, not a separate read first.
    request = _sample_request("rider-save-if-open-false")
    other = _sample_request("rider-save-if-open-false-2")
    store = RequestStore(make_session_factory())
    store.add(request)
    store.add(other)

    # A different writer gets there first, for real, in the store.
    already_matched = RequestStore(make_session_factory()).get(request.id)
    already_matched.status = RequestStatus.MATCHED
    already_matched.matched_with = other.id
    already_matched.status_changed_at = datetime.utcnow()
    RequestStore(make_session_factory()).save(already_matched)

    # `request` is still the stale, pre-match, OPEN-looking local object.
    request.status = RequestStatus.CANCELLED
    request.matched_with = None
    request.status_changed_at = datetime.utcnow()
    assert store.save_if_open(request) is False

    fetched = store.get(request.id)
    assert fetched.status == RequestStatus.MATCHED
    assert fetched.matched_with == other.id


def test_save_pair_if_both_open_writes_both_and_returns_true_when_both_are_still_open():
    request_a = _sample_request("rider-save-pair-true-a")
    request_b = _sample_request("rider-save-pair-true-b")
    store = RequestStore(make_session_factory())
    store.add(request_a)
    store.add(request_b)

    matched_at = datetime.utcnow()
    request_a.status = RequestStatus.MATCHED
    request_a.matched_with = request_b.id
    request_a.status_changed_at = matched_at
    request_b.status = RequestStatus.MATCHED
    request_b.matched_with = request_a.id
    request_b.status_changed_at = matched_at

    assert store.save_pair_if_both_open(request_a, request_b) is True

    assert store.get(request_a.id).status == RequestStatus.MATCHED
    assert store.get(request_a.id).matched_with == request_b.id
    assert store.get(request_b.id).status == RequestStatus.MATCHED
    assert store.get(request_b.id).matched_with == request_a.id


def test_save_pair_if_both_open_writes_neither_and_returns_false_when_either_is_not_open():
    # The exact case this method exists for: one side (request_b) was
    # already flipped away from OPEN by a different, real writer. A pair of
    # separate save() calls would still blindly overwrite request_b's real
    # status and would already have committed request_a's own write by the
    # time anyone could notice -- this has to roll back *both* sides
    # together, leaving request_a's stored row untouched too, not just
    # refuse request_b's.
    request_a = _sample_request("rider-save-pair-false-a")
    request_b = _sample_request("rider-save-pair-false-b")
    other = _sample_request("rider-save-pair-false-other")
    store = RequestStore(make_session_factory())
    store.add(request_a)
    store.add(request_b)
    store.add(other)

    already_cancelled = RequestStore(make_session_factory()).get(request_b.id)
    already_cancelled.status = RequestStatus.CANCELLED
    already_cancelled.status_changed_at = datetime.utcnow()
    RequestStore(make_session_factory()).save(already_cancelled)

    # request_a/request_b are still the stale, pre-cancel, OPEN-looking
    # local objects a caller would have mutated in place before writing.
    matched_at = datetime.utcnow()
    request_a.status = RequestStatus.MATCHED
    request_a.matched_with = request_b.id
    request_a.status_changed_at = matched_at
    request_b.status = RequestStatus.MATCHED
    request_b.matched_with = request_a.id
    request_b.status_changed_at = matched_at

    assert store.save_pair_if_both_open(request_a, request_b) is False

    fetched_a = store.get(request_a.id)
    assert fetched_a.status == RequestStatus.OPEN
    assert fetched_a.matched_with is None
    fetched_b = store.get(request_b.id)
    assert fetched_b.status == RequestStatus.CANCELLED
    assert fetched_b.matched_with is None

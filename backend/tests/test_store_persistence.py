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

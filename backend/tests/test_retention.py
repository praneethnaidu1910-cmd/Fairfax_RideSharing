"""TASKS.md #17 -- data retention for matched/cancelled/expired requests.

Covers app/retention.py's policy functions directly, and the actual
mutation (app/store.py's RequestStore.anonymize_stale()) against a real
Postgres row, the same "prove it actually runs" bar TASKS.md's own rules
ask for rather than a comment saying it should.
"""

from datetime import datetime, timedelta

from app.db import make_session_factory
from app.retention import RETENTION_DAYS, is_due_for_anonymization, terminal_at
from app.schemas import Location, OneOffSchedule, RequestStatus, RideRequest
from app.store import RequestStore


def _sample_request(rider_id: str, **overrides) -> RideRequest:
    earliest = overrides.pop("earliest_departure", datetime.utcnow() + timedelta(hours=1))
    latest = overrides.pop("latest_departure", earliest + timedelta(minutes=30))
    defaults = dict(
        rider_id=rider_id,
        origin=Location(lat=38.8462, lng=-77.3064),
        destination=Location(lat=38.9757, lng=-77.6122),
        schedule=OneOffSchedule(earliest_departure=earliest, latest_departure=latest),
        seats_needed=1,
        contact="555-0199",
    )
    defaults.update(overrides)
    return RideRequest(**defaults)


# -- app/retention.py's policy functions, no database involved --


def test_terminal_at_is_none_for_a_still_open_unexpired_request():
    request = _sample_request("rider-retention-open")
    assert terminal_at(request) is None


def test_terminal_at_uses_status_changed_at_for_matched():
    matched_at = datetime.utcnow() - timedelta(days=1)
    request = _sample_request(
        "rider-retention-matched", status=RequestStatus.MATCHED, status_changed_at=matched_at
    )
    assert terminal_at(request) == matched_at


def test_terminal_at_uses_status_changed_at_for_cancelled():
    cancelled_at = datetime.utcnow() - timedelta(days=1)
    request = _sample_request(
        "rider-retention-cancelled",
        status=RequestStatus.CANCELLED,
        status_changed_at=cancelled_at,
    )
    assert terminal_at(request) == cancelled_at


def test_terminal_at_uses_latest_departure_for_an_expired_open_request():
    now = datetime.utcnow()
    past_window_start = now - timedelta(days=40)
    request = _sample_request(
        "rider-retention-expired",
        earliest_departure=past_window_start,
        latest_departure=past_window_start + timedelta(minutes=30),
    )
    assert terminal_at(request, now) == request.schedule.latest_departure


def test_is_due_for_anonymization_true_once_retention_window_has_passed():
    now = datetime.utcnow()
    matched_at = now - timedelta(days=RETENTION_DAYS, hours=1)
    request = _sample_request(
        "rider-retention-due", status=RequestStatus.MATCHED, status_changed_at=matched_at
    )
    assert is_due_for_anonymization(request, now) is True


def test_is_due_for_anonymization_false_before_retention_window_passes():
    now = datetime.utcnow()
    matched_at = now - timedelta(days=RETENTION_DAYS - 1)
    request = _sample_request(
        "rider-retention-not-due", status=RequestStatus.MATCHED, status_changed_at=matched_at
    )
    assert is_due_for_anonymization(request, now) is False


def test_is_due_for_anonymization_false_once_already_anonymized():
    now = datetime.utcnow()
    matched_at = now - timedelta(days=RETENTION_DAYS + 5)
    request = _sample_request(
        "rider-retention-already-done",
        status=RequestStatus.MATCHED,
        status_changed_at=matched_at,
        anonymized_at=now - timedelta(days=1),
    )
    assert is_due_for_anonymization(request, now) is False


# -- RequestStore.anonymize_stale(): the real mutation, against Postgres --


def test_anonymize_stale_scrubs_a_long_matched_requests_location_and_contact():
    now = datetime.utcnow()
    matched_at = now - timedelta(days=RETENTION_DAYS + 1)
    request = _sample_request(
        "rider-retention-store-matched",
        status=RequestStatus.MATCHED,
        status_changed_at=matched_at,
    )
    original_lat, original_lng = request.origin.lat, request.origin.lng

    store = RequestStore(make_session_factory())
    store.add(request)

    anonymized_count = store.anonymize_stale(now=now)
    assert anonymized_count == 1

    fetched = store.get(request.id)
    assert fetched is not None
    assert fetched.contact == ""
    assert fetched.anonymized_at == now
    # Scrubbed to the neighborhood cell's center, not the original precise
    # point -- not asserting an exact value (that's app.geo.cell_center's
    # own job to get right), just that the real one is gone.
    assert (fetched.origin.lat, fetched.origin.lng) != (original_lat, original_lng)
    # Still a real, usable area-level location, not a null/placeholder --
    # same H3 cell the request's own coarse area was always in.
    assert fetched.origin.coarse_cell() == Location(
        lat=original_lat, lng=original_lng
    ).coarse_cell()


def test_anonymize_stale_leaves_a_recently_matched_request_untouched():
    request = _sample_request(
        "rider-retention-store-recent",
        status=RequestStatus.MATCHED,
        status_changed_at=datetime.utcnow(),
    )
    store = RequestStore(make_session_factory())
    store.add(request)

    anonymized_count = store.anonymize_stale()
    assert anonymized_count == 0

    fetched = store.get(request.id)
    assert fetched is not None
    assert fetched.contact == "555-0199"
    assert fetched.anonymized_at is None


def test_anonymize_stale_leaves_a_still_open_request_untouched():
    request = _sample_request("rider-retention-store-open")
    store = RequestStore(make_session_factory())
    store.add(request)

    anonymized_count = store.anonymize_stale()
    assert anonymized_count == 0

    fetched = store.get(request.id)
    assert fetched is not None
    assert fetched.contact == "555-0199"


def test_anonymize_stale_is_idempotent_across_repeated_runs():
    now = datetime.utcnow()
    matched_at = now - timedelta(days=RETENTION_DAYS + 1)
    request = _sample_request(
        "rider-retention-store-idempotent",
        status=RequestStatus.MATCHED,
        status_changed_at=matched_at,
    )
    store = RequestStore(make_session_factory())
    store.add(request)

    first_run_count = store.anonymize_stale(now=now)
    assert first_run_count == 1

    # A second run, even much later, shouldn't re-process (and
    # re-timestamp) a row already anonymized.
    second_run_count = store.anonymize_stale(now=now + timedelta(days=10))
    assert second_run_count == 0

    fetched = store.get(request.id)
    assert fetched is not None
    assert fetched.anonymized_at == now

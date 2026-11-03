"""Data retention policy (TASKS.md #17).

SCOPE.md's "part that isn't just an engineering decision" names "real data
protection for real location data" as a real requirement -- right now a
matched/cancelled/expired request's precise location and contact just sit
in Postgres forever with nothing ever cleaning them up. This module is the
one place that decides *when* a request's precise data is stale enough to
scrub; app/store.py's RequestStore.anonymize_stale() is the one place that
actually does the scrubbing.

RETENTION_DAYS has no value SCOPE.md specifies -- there's no stated legal
or product requirement for the exact number, so 30 is my own reasonable
default (common data-minimization practice for data that's no longer
needed for its original purpose), worth revisiting if a real policy is
ever set.
"""

from datetime import datetime, timedelta
from typing import Optional

from app.matching.scoring import is_expired
from app.schemas import OneOffSchedule, RequestStatus, RideRequest

RETENTION_DAYS = 30


def terminal_at(request: RideRequest, now: Optional[datetime] = None) -> Optional[datetime]:
    """When `request` stopped being matchable, or None if it still is.

    - MATCHED/CANCELLED: `status_changed_at`, written by whatever flipped
      the status (MatchingEngine for a match, the cancel route for a
      cancel) -- see app/schemas.py's RideRequest.
    - OPEN: only "terminal" if TASKS.md #14's is_expired() says its window
      has passed, in which case that window's own `latest_departure` is
      the moment it became stale -- a RecurringSchedule never expires this
      way (docs/MATCHING_ALGORITHM.md's "Request lifecycle" section), so
      is_expired() already returns False for one and this never fires.
    - Still-open and not expired: not terminal yet, returns None.
    """
    if request.status in (RequestStatus.MATCHED, RequestStatus.CANCELLED):
        return request.status_changed_at
    if request.status == RequestStatus.OPEN and is_expired(request, now):
        assert isinstance(request.schedule, OneOffSchedule)
        return request.schedule.latest_departure
    return None


def is_due_for_anonymization(request: RideRequest, now: Optional[datetime] = None) -> bool:
    """Whether `request`'s precise location/contact should be scrubbed.

    Already-anonymized requests are never due again -- this keeps
    RequestStore.anonymize_stale() idempotent across repeated runs instead
    of re-processing (and re-timestamping) the same row forever.
    """
    if request.anonymized_at is not None:
        return False
    now = now or datetime.utcnow()
    became_terminal = terminal_at(request, now)
    if became_terminal is None:
        return False
    return now - became_terminal >= timedelta(days=RETENTION_DAYS)

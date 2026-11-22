"""Postgres-backed store of every RideRequest ever created, keyed by id
(TASKS.md #9 -- replaces the original in-memory dict so requests survive a
server restart instead of vanishing). Schema lives in migrations/, applied
with `alembic upgrade head`, not `Base.metadata.create_all()`.

Still separate from MatchingEngine._unmatched, which only tracks requests
that haven't matched yet, purely for bucketing candidates, and stays
in-memory/ephemeral by design -- rebuilding that pool from the DB on
startup isn't part of this task (TASKS.md #9 only asks for GET
/requests[/{id}] to survive a restart, not for the live matching pool to
resume mid-flight). GET /requests and GET /requests/{id} need every
request regardless of status, durably, which is what this file provides.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.orm import sessionmaker

from app.geo import cell_center
from app.models import RideRequestORM
from app.retention import is_due_for_anonymization
from app.schemas import (
    Location,
    OneOffSchedule,
    RecurringSchedule,
    RequestStatus,
    RideRequest,
)


def _schedule_to_row(schedule: "OneOffSchedule | RecurringSchedule") -> tuple[str, dict]:
    if isinstance(schedule, OneOffSchedule):
        return "one_off", schedule.model_dump(mode="json")
    return "recurring", schedule.model_dump(mode="json")


def _row_to_schedule(schedule_type: str, payload: dict) -> "OneOffSchedule | RecurringSchedule":
    if schedule_type == "one_off":
        return OneOffSchedule(**payload)
    return RecurringSchedule(**payload)


def _to_orm(request: RideRequest) -> RideRequestORM:
    schedule_type, schedule_payload = _schedule_to_row(request.schedule)
    return RideRequestORM(
        id=request.id,
        rider_id=request.rider_id,
        origin_lat=request.origin.lat,
        origin_lng=request.origin.lng,
        destination_lat=request.destination.lat,
        destination_lng=request.destination.lng,
        schedule_type=schedule_type,
        schedule=schedule_payload,
        seats_needed=request.seats_needed,
        contact=request.contact,
        status=request.status.value,
        posted_at=request.posted_at,
        matched_with=request.matched_with,
        status_changed_at=request.status_changed_at,
        anonymized_at=request.anonymized_at,
    )


def _from_orm(row: RideRequestORM) -> RideRequest:
    return RideRequest(
        id=row.id,
        rider_id=row.rider_id,
        origin=Location(lat=row.origin_lat, lng=row.origin_lng),
        destination=Location(lat=row.destination_lat, lng=row.destination_lng),
        schedule=_row_to_schedule(row.schedule_type, row.schedule),
        seats_needed=row.seats_needed,
        contact=row.contact,
        status=RequestStatus(row.status),
        posted_at=row.posted_at,
        matched_with=row.matched_with,
        status_changed_at=row.status_changed_at,
        anonymized_at=row.anonymized_at,
    )


class RequestStore:
    def __init__(self, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory

    def add(self, request: RideRequest) -> None:
        with self._session_factory() as session:
            session.add(_to_orm(request))
            session.commit()

    def save(self, request: RideRequest) -> None:
        """Persist a mutation MatchingEngine already made in place on this
        request (status/matched_with flipping to `matched`) -- called by
        the engine right after it flips those fields, so a match survives
        a restart too, not just the original open request."""
        with self._session_factory() as session:
            row = session.get(RideRequestORM, request.id)
            if row is None:
                session.add(_to_orm(request))
            else:
                row.status = request.status.value
                row.matched_with = request.matched_with
                row.status_changed_at = request.status_changed_at
            session.commit()

    def save_if_open(self, request: RideRequest) -> bool:
        """Same write as save() (persisting a status/matched_with/
        status_changed_at transition already made in place on `request`),
        but as a single conditional UPDATE -- `WHERE status = 'open'` --
        instead of a separate read-then-write.

        save() alone blindly overwrites whatever status is currently
        stored, no matter how long ago `request` was actually read. A
        caller that first re-reads the row and checks its status before
        calling save() (POST /requests/{id}/cancel's cancel_request() used
        to do exactly this, as a second "recheck right before writing")
        only narrows that gap, it doesn't close it: there's always some
        nonzero time between that re-read returning and save()'s own
        commit, and a concurrent writer -- the matching engine flipping
        this exact request to MATCHED, say -- can still land in it.
        Confirmed real, not theoretical, with a live script before this
        fix: paused cancel_request() right after its own second re-read/
        recheck (both already OPEN), ran a real on_new_request() match
        against the same request from a concurrent thread in that gap
        (flipping its stored status to MATCHED for real), then let the
        stale cancel resume -- it still wrote CANCELLED over the real
        match, wiping matched_with back to None, while the matched
        counterpart's own row kept pointing back at it as MATCHED.

        A single `UPDATE ... WHERE status = 'open'` has no such gap:
        Postgres's own row-level locking serializes two concurrent writers
        against the same row, and whichever one commits second has its
        WHERE clause evaluated against the winner's already-committed row,
        not against whatever either side happened to read before either
        one wrote. Returns True if the write actually took effect (the row
        was still OPEN at the moment of the UPDATE), False if it had
        already moved away from OPEN by then -- the caller lost the race
        and must not treat `request`'s in-memory status as what actually
        got stored.
        """
        with self._session_factory() as session:
            result = session.execute(
                update(RideRequestORM)
                .where(
                    RideRequestORM.id == request.id,
                    RideRequestORM.status == RequestStatus.OPEN.value,
                )
                .values(
                    status=request.status.value,
                    matched_with=request.matched_with,
                    status_changed_at=request.status_changed_at,
                )
            )
            session.commit()
            return result.rowcount > 0

    def save_pair_if_both_open(self, request_a: RideRequest, request_b: RideRequest) -> bool:
        """The matching engine's own counterpart to save_if_open() above --
        a match is always a *pair* of writes (both sides flip OPEN ->
        MATCHED together), and save_if_open()'s single-row atomicity alone
        doesn't make writing two rows, one call each, atomic as a pair.

        MatchingEngine.on_new_request() already rechecks both sides of a
        pending match against the store right before committing it,
        specifically to catch a concurrent cancel of either side landing
        mid-scoring (see its own two "store-backed race" comments). But
        "recheck right before writing" has the exact same shape of gap
        save_if_open()'s own docstring already describes for
        cancel_request(): there's still a nonzero gap between that last
        recheck returning and the actual write landing, and a cancel can
        land in *that* gap too, just a narrower one than the gap those two
        rechecks already close. Confirmed real, not theoretical, with a
        live script before this fix: paused on_new_request() right after
        its own second recheck passed (both sides still OPEN) but before
        its matched_at write, ran the real cancel_request() sequence
        against the pooled candidate from a concurrent thread in that
        exact gap (a genuine cancel, committed for real), then let
        on_new_request() resume into two separate save() calls -- it still
        wrote MATCHED over the real cancel for both sides, silently
        reverting a cancel the poster already got a 200 for, and then
        crashed with an unhandled `ValueError: list.remove(x): x not in
        list`, since cancel_request()'s own remove_from_pool() had already
        dropped the candidate the engine still expected to find.

        A single transaction holding two conditional `UPDATE ... WHERE
        status = 'open'` statements, committed only if *both* affected a
        row and rolled back (so neither takes effect) if either didn't,
        closes this the same way save_if_open()'s single conditional
        UPDATE closes the single-row version: Postgres's own row-level
        locking means whichever side a concurrent cancel reaches first is
        either already committed (so this UPDATE's own WHERE clause
        correctly sees it as no-longer-open and affects zero rows) or gets
        blocked until this transaction ends (so there's no window for it
        to land silently in between two separate commits). Returns whether
        the match write actually took effect for *both* sides -- if not,
        the caller must not treat `request_a`/`request_b`'s in-memory
        MATCHED status as what actually got stored for either one.
        """
        with self._session_factory() as session:
            result_a = session.execute(
                update(RideRequestORM)
                .where(
                    RideRequestORM.id == request_a.id,
                    RideRequestORM.status == RequestStatus.OPEN.value,
                )
                .values(
                    status=request_a.status.value,
                    matched_with=request_a.matched_with,
                    status_changed_at=request_a.status_changed_at,
                )
            )
            result_b = session.execute(
                update(RideRequestORM)
                .where(
                    RideRequestORM.id == request_b.id,
                    RideRequestORM.status == RequestStatus.OPEN.value,
                )
                .values(
                    status=request_b.status.value,
                    matched_with=request_b.matched_with,
                    status_changed_at=request_b.status_changed_at,
                )
            )
            if result_a.rowcount > 0 and result_b.rowcount > 0:
                session.commit()
                return True
            session.rollback()
            return False

    def get(self, request_id: UUID) -> Optional[RideRequest]:
        with self._session_factory() as session:
            row = session.get(RideRequestORM, request_id)
            return _from_orm(row) if row is not None else None

    def list_open(self) -> list[RideRequest]:
        with self._session_factory() as session:
            rows = (
                session.query(RideRequestORM)
                .filter(RideRequestORM.status == RequestStatus.OPEN.value)
                .all()
            )
            return [_from_orm(row) for row in rows]

    def anonymize_stale(self, now: Optional[datetime] = None) -> int:
        """Overwrites precise origin/destination and contact for every
        request app.retention.is_due_for_anonymization() says is past its
        retention window (TASKS.md #17) -- replaces the exact pickup/
        dropoff point with its own neighborhood-level H3 cell center
        (app.geo.cell_center(), the same granularity SCOPE.md already
        treats as safe to show everyone pre-match) and `contact` with an
        empty string, then stamps `anonymized_at` so a later run skips it
        instead of re-processing it.

        Only scans rows not yet anonymized -- cheap and idempotent to call
        repeatedly. There's no in-app scheduler calling this on its own
        (same "no cron/background job" posture as TASKS.md #14, except
        this one mutates stored rows rather than just computing a display
        value, so it needs a real external trigger -- see
        scripts/anonymize_stale_requests.py and the README's "Data
        retention" section for how to run it periodically).
        """
        now = now or datetime.utcnow()
        anonymized_count = 0
        with self._session_factory() as session:
            rows = (
                session.query(RideRequestORM)
                .filter(RideRequestORM.anonymized_at.is_(None))
                .all()
            )
            for row in rows:
                request = _from_orm(row)
                if not is_due_for_anonymization(request, now):
                    continue
                origin_lat, origin_lng = cell_center(request.origin.coarse_cell())
                destination_lat, destination_lng = cell_center(
                    request.destination.coarse_cell()
                )
                row.origin_lat = origin_lat
                row.origin_lng = origin_lng
                row.destination_lat = destination_lat
                row.destination_lng = destination_lng
                row.contact = ""
                row.anonymized_at = now
                anonymized_count += 1
            session.commit()
        return anonymized_count

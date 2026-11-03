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

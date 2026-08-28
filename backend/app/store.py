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

from typing import Optional
from uuid import UUID

from sqlalchemy.orm import sessionmaker

from app.models import RideRequestORM
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

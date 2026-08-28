"""SQLAlchemy ORM model backing app/store.py's RequestStore (TASKS.md #9).

One table, `ride_requests`, mirrors app/schemas.py's RideRequest field for
field, except the schedule union: `schedule_type` ("one_off"/"recurring")
plus a JSON `schedule` column stand in for Pydantic's
`Union[OneOffSchedule, RecurringSchedule]`, since a SQL column can't be a
union -- app/store.py's `_to_orm`/`_from_orm` are the one place that
conversion happens.
"""

import uuid

from sqlalchemy import Column, DateTime, Float, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID

from app.db import Base


class RideRequestORM(Base):
    __tablename__ = "ride_requests"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    rider_id = Column(String, nullable=False)
    origin_lat = Column(Float, nullable=False)
    origin_lng = Column(Float, nullable=False)
    destination_lat = Column(Float, nullable=False)
    destination_lng = Column(Float, nullable=False)
    schedule_type = Column(String, nullable=False)
    schedule = Column(JSONB, nullable=False)
    seats_needed = Column(Integer, nullable=False, default=1)
    contact = Column(String, nullable=False)
    status = Column(String, nullable=False, default="open")
    posted_at = Column(DateTime(timezone=False), nullable=False)
    matched_with = Column(PGUUID(as_uuid=True), nullable=True)

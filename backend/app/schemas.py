from datetime import datetime, time
from enum import Enum
from typing import Union
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator

from app.geo import h3_cell


class Location(BaseModel):
    lat: float
    lng: float

    def coarse_cell(self) -> str:
        """Neighborhood-level H3 cell -- what other users see pre-match."""
        return h3_cell(self.lat, self.lng)


class OneOffSchedule(BaseModel):
    earliest_departure: datetime
    latest_departure: datetime

    @model_validator(mode="after")
    def _check_window(self) -> "OneOffSchedule":
        if self.latest_departure < self.earliest_departure:
            raise ValueError("latest_departure must not be before earliest_departure")
        return self


class RecurringSchedule(BaseModel):
    # Monday=0 .. Sunday=6, matching datetime.date.weekday()
    weekdays: list[int]
    earliest_departure_time: time
    latest_departure_time: time

    @model_validator(mode="after")
    def _check_weekdays_and_window(self) -> "RecurringSchedule":
        if not self.weekdays:
            raise ValueError("recurring schedule needs at least one weekday")
        if any(day < 0 or day > 6 for day in self.weekdays):
            raise ValueError("weekdays must be 0 (Monday) through 6 (Sunday)")
        if self.latest_departure_time < self.earliest_departure_time:
            raise ValueError(
                "latest_departure_time must not be before earliest_departure_time"
            )
        return self


class RequestStatus(str, Enum):
    OPEN = "open"
    MATCHED = "matched"
    EXPIRED = "expired"


class RideRequest(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    rider_id: str
    origin: Location
    destination: Location
    # One-off window or a recurring weekday pattern -- never both.
    schedule: Union[OneOffSchedule, RecurringSchedule]
    seats_needed: int = Field(default=1, ge=1)
    # Collected at request time so a match can reach the other party; must
    # not appear in any pre-match serialized response (TASKS.md #6).
    contact: str
    status: RequestStatus = RequestStatus.OPEN
    posted_at: datetime = Field(default_factory=datetime.utcnow)


class MatchGroup(BaseModel):
    request_ids: list[UUID]
    score: float
    reason: str

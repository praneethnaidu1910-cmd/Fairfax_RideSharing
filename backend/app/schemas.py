from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class Location(BaseModel):
    lat: float
    lng: float


class RideRequest(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    rider_id: str
    origin: Location
    destination: Location
    earliest_departure: datetime
    latest_departure: datetime
    seats_needed: int = 1
    posted_at: datetime = Field(default_factory=datetime.utcnow)


class MatchGroup(BaseModel):
    request_ids: list[UUID]
    score: float
    reason: str

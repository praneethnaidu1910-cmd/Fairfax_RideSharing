from typing import Literal

from pydantic import BaseModel, Field


class Location(BaseModel):
    # Real-world bounds, same fix and same reasoning as app/schemas.py's
    # Location (TASKS.md's "Reject physically-impossible coordinates"
    # entry): without this, a rider_location like lat=999 was silently
    # accepted and fed straight into haversine_miles() -- math.sin/cos
    # don't care that 999 degrees isn't a real latitude, so POST /match
    # would happily return a "nearest" driver computed from a nonsense
    # distance instead of rejecting the impossible point at intake. This
    # module has its own Location (deliberately not wired to the pooling
    # engine's), so it needed its own copy of the same fix.
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class Driver(BaseModel):
    id: str
    name: str
    location: Location
    status: Literal["available", "busy"]


class MatchRequest(BaseModel):
    rider_location: Location


class MatchResult(BaseModel):
    driver_id: str
    driver_name: str
    driver_location: Location
    distance_miles: float

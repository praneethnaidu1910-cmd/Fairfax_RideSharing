from typing import Literal

from pydantic import BaseModel


class Location(BaseModel):
    lat: float
    lng: float


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

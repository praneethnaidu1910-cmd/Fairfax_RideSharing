"""Nearest-available-driver matching for the dispatch demo.

Real geospatial distance (haversine great-circle distance), not a flat
Euclidean approximation -- lat/lng degrees aren't equally spaced in miles,
so a naive distance formula would misrank drivers, especially east-west.
"""

import math

from app.dispatch.schemas import Driver, Location

EARTH_RADIUS_MILES = 3958.8


def haversine_miles(a: Location, b: Location) -> float:
    lat1, lng1, lat2, lng2 = map(math.radians, (a.lat, a.lng, b.lat, b.lng))
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(h))


def find_nearest_available_driver(
    rider_location: Location, drivers: list[Driver]
) -> tuple[Driver, float] | None:
    available = [d for d in drivers if d.status == "available"]
    if not available:
        return None

    nearest = min(available, key=lambda d: haversine_miles(rider_location, d.location))
    distance = haversine_miles(rider_location, nearest.location)
    return nearest, distance

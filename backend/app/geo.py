"""Shared geo helpers: H3 indexing, distance, and bearing.

One H3 cell computation, reused for two purposes (per TASKS.md #1/#2): the
"coarse area" shown to other users pre-match, and the bucketing key used for
candidate reduction in the matching engine. Keeping it here means both call
the same function instead of growing two geocoding schemes.

haversine_miles/bearing_degrees take raw lat/lng floats rather than a
Location, so this module has no dependency on app.schemas (which imports
h3_cell from here) -- avoids a circular import. The dispatch side-module
(app/dispatch/matching.py) has its own haversine by design (TASKS.md: "own
schemas, own router, own tests, not wired into" the pooling engine); this
one is the pooling engine's, used by app/matching/scoring.py.
"""

import math

import h3

# Resolution ~8 (~460m edge) per docs/MATCHING_ALGORITHM.md's bucketing design.
COARSE_RESOLUTION = 8

EARTH_RADIUS_MILES = 3958.8


def h3_cell(lat: float, lng: float, resolution: int = COARSE_RESOLUTION) -> str:
    return h3.latlng_to_cell(lat, lng, resolution)


def haversine_miles(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in miles -- not a flat lat/lng approximation,
    which misranks pairs because a degree of longitude isn't a fixed
    distance (same reasoning as app/dispatch/matching.py's haversine)."""
    rlat1, rlng1, rlat2, rlng2 = map(math.radians, (lat1, lng1, lat2, lng2))
    dlat = rlat2 - rlat1
    dlng = rlng2 - rlng1
    h = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlng / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(h))


def bearing_degrees(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Initial compass bearing (0-360) from point 1 to point 2."""
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlng = math.radians(lng2 - lng1)
    x = math.sin(dlng) * math.cos(rlat2)
    y = math.cos(rlat1) * math.sin(rlat2) - math.sin(rlat1) * math.cos(rlat2) * math.cos(dlng)
    return (math.degrees(math.atan2(x, y)) + 360) % 360

"""Geocoding: informal place names -> coordinates (TASKS.md #10).

Wraps Nominatim (OpenStreetMap) -- free, no API key, consistent with
SCOPE.md's no-cost stance. Sits in *front of* the existing POST /requests
shape rather than inside it: RideRequestCreate still takes a precise
Location, and this module is what a caller (the frontend, TASKS.md #11)
uses first to turn a free-text place name like "GMU" or "Fairfax Corner"
into one, before it ever reaches that endpoint.

Per TASKS.md #10's decision: this sandbox's own network policy denies
nominatim.openstreetmap.org outright (a 403 at the egress gateway, not a
timeout or a Nominatim-side rate limit), so automated runs can only test
this module with the real HTTP call mocked -- see tests/test_geocoding.py.
The real endpoint gets verified by hand, once, in an interactive session
with normal network access, per that same note.
"""

import time

import httpx

from app.schemas import Location

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

# Nominatim's usage policy requires a real identifying User-Agent, not a
# browser spoof: https://operations.osmfoundation.org/policies/nominatim/
USER_AGENT = "fairfax-ridesharing-demo/1.0 (contact: praneethnaidu1910@gmail.com)"

# left,top,right,bottom -- covers every town SCOPE.md names (Fairfax,
# Ashburn, Herndon, Chantilly, Reston, Aldie, Manassas, Sterling, South
# Riding, Vienna, Falls Church, Centerville) with margin, and nothing else.
# Combined with bounded=1 below, this is what turns "Fairfax" into the one
# in Virginia instead of a same-named place elsewhere -- the "never a
# silent wrong-location match" half of this task's acceptance criterion.
VIRGINIA_VIEWBOX = "-77.75,39.10,-77.10,38.60"

REQUEST_TIMEOUT_SECONDS = 5.0

# Nominatim's usage policy caps free use at 1 request/second.
MIN_SECONDS_BETWEEN_REQUESTS = 1.0

_last_request_at: float = 0.0


class PlaceNotFoundError(ValueError):
    """Raised when Nominatim has no match for the given place name, or the
    input isn't a place name at all -- callers should surface this as a
    clear error, never fall back to a guessed location."""


def _wait_for_rate_limit() -> None:
    global _last_request_at
    elapsed = time.monotonic() - _last_request_at
    if elapsed < MIN_SECONDS_BETWEEN_REQUESTS:
        time.sleep(MIN_SECONDS_BETWEEN_REQUESTS - elapsed)
    _last_request_at = time.monotonic()


def geocode_place(place_name: str) -> Location:
    """Resolve a free-text place name to coordinates, or raise
    PlaceNotFoundError -- never returns a guessed/default location."""
    if not place_name or not place_name.strip():
        raise PlaceNotFoundError("place name must not be empty")

    _wait_for_rate_limit()
    response = httpx.get(
        NOMINATIM_URL,
        params={
            "q": place_name,
            "format": "json",
            "limit": 1,
            "viewbox": VIRGINIA_VIEWBOX,
            "bounded": 1,
        },
        headers={"User-Agent": USER_AGENT},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    results = response.json()
    if not results:
        raise PlaceNotFoundError(f"no match for {place_name!r} in the Northern Virginia area")

    top = results[0]
    return Location(lat=float(top["lat"]), lng=float(top["lon"]))

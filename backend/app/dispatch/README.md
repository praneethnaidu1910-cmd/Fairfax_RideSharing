# Dispatch demo (nearest-available-driver)

A small, separate module from the ride-pooling engine described in the
[root README](../../../README.md) and [SCOPE.md](../../../SCOPE.md). Where
the pooling engine matches riders to *other riders* going the same way,
this module is the more familiar Uber-style problem: match one rider to
the *nearest available driver* in a fixed fleet. It exists here as a
smaller, self-contained warm-up slice — not a replacement for the pooling
work, and not wired into it (own schemas, own router, own tests).

## What this does

- `POST /match` takes a rider's `{lat, lng}` and returns the nearest
  driver whose status is `available`, using real haversine great-circle
  distance — not a flat lat/lng Euclidean approximation, which misranks
  drivers because a degree of longitude isn't a fixed distance.
- Filters out `busy` drivers even when they're geographically closer than
  the nearest available one (see
  [test_excludes_busy_drivers_even_if_closer](../../tests/test_dispatch_matching.py)).
- Returns `404` when no driver in the fleet is available, rather than
  silently matching a busy one.
- Fleet is 18 seeded `Driver` records (`sample_drivers.py`) across the
  Fairfax/Reston/Herndon/Chantilly/Ashburn demo area, held in memory.

## What this deliberately does not do (yet)

- **No persistence.** The fleet is a hardcoded Python list, reset on every
  process restart. There's no database because the interesting problem
  tonight is the distance/matching logic, not CRUD.
- **No driver state changes.** A match doesn't flip the driver to `busy`
  — this is a read-only "who's nearest" query, not a booking system. Ride
  lifecycle (accept, start, complete, driver goes busy/free again) is out
  of scope.
- **No auth, no payments, no notifications.** Nothing here represents a
  real driver or a real transaction.
- **No routing/ETA.** Distance is straight-line haversine, not
  road-network distance or drive time. A real routing API would be needed
  for that and costs money/needs real map data — not worth it to
  demonstrate the matching logic.
- **No ties/multi-candidate logic.** On exact distance ties, whichever
  driver sorts first wins (Python's `min()` is stable); there's no
  secondary ranking (e.g. driver rating, idle time).

## Running it

```bash
cd backend
python -m venv .venv
./.venv/Scripts/activate  # or source .venv/bin/activate on macOS/Linux
pip install -r requirements.txt
uvicorn app.main:app --reload
```

```bash
curl -X POST http://127.0.0.1:8000/match \
  -H "Content-Type: application/json" \
  -d '{"rider_location": {"lat": 38.96, "lng": -77.355}}'
```

## Tests

```bash
cd backend
pytest tests/test_dispatch_matching.py tests/test_dispatch_api.py -v
```

Covers: haversine correctness (zero-distance, known distance, symmetry),
nearest-driver selection, busy-driver exclusion, the no-driver-available
case, request validation, and the 404 path through the actual HTTP route.

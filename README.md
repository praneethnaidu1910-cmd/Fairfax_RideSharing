# Ride-Pooling Matching Engine (Demo)

A local, non-deployed technical demo of a ride-pooling matching engine —
built to solve a specific, real problem: coordinating shared rides among
~1,000 people across Fairfax, Ashburn, Herndon, Chantilly, and Reston, VA,
currently done by scrolling a WhatsApp group and hoping you spot a
compatible request in time.

This is not a clone of Uber/Lyft. There are no live drivers, no live
riders, and no real transactions — see [SCOPE.md](SCOPE.md) for exactly
what this is and isn't. The interesting part is the matching logic (real
geospatial + temporal compatibility scoring, not a database query) and the
real-time architecture (incremental matching over a stream, not polling).
Design details: [docs/MATCHING_ALGORITHM.md](docs/MATCHING_ALGORITHM.md).

## Status

Scaffolding stage — see [TASKS.md](TASKS.md) for the build backlog and
what's done so far.

## Dispatch demo (separate side module)

`backend/app/dispatch/` is a smaller, self-contained module that solves a
different, more familiar problem: matching one rider to the nearest
*available driver* in a fixed fleet (haversine distance, not the
rider-to-rider pooling this project is really about). It's a warm-up
slice, not a replacement for the pooling engine above — see its own
[README](backend/app/dispatch/README.md) for exactly what it does and
doesn't do.

## Running locally

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload
```

```bash
cd backend
pytest
```

## Manual smoke test: structured intake + live matches

With the server running (`uvicorn app.main:app --reload` from `backend/`),
open a WebSocket subscriber first so you can watch a match arrive, then post
two compatible requests from another terminal.

```bash
# Terminal 1 -- subscribe to match events (websocat, or any WS client)
websocat ws://127.0.0.1:8000/matches
```

```bash
# Terminal 2 -- two riders on the same Fairfax->Aldie corridor, overlapping
# windows, close-but-not-identical origins
curl -X POST http://127.0.0.1:8000/requests \
  -H "Content-Type: application/json" \
  -d '{
        "rider_id": "rider-a",
        "origin": {"lat": 38.8462, "lng": -77.3064},
        "destination": {"lat": 38.9757, "lng": -77.6122},
        "schedule": {"earliest_departure": "2026-01-01T14:00:00", "latest_departure": "2026-01-01T14:30:00"},
        "seats_needed": 1,
        "contact": "555-0101"
      }'

curl -X POST http://127.0.0.1:8000/requests \
  -H "Content-Type: application/json" \
  -d '{
        "rider_id": "rider-b",
        "origin": {"lat": 38.8500, "lng": -77.3100},
        "destination": {"lat": 38.9757, "lng": -77.6122},
        "schedule": {"earliest_departure": "2026-01-01T14:05:00", "latest_departure": "2026-01-01T14:35:00"},
        "seats_needed": 1,
        "contact": "555-0102"
      }'

# Should show both requests, coarse area + fuzzed window only -- no
# origin/destination lat-lng and no contact field.
curl http://127.0.0.1:8000/requests
```

Terminal 1 should print a `MatchGroup` event (both request ids, a score, and
a reason) shortly after the second `POST` -- that's the incremental matching
engine (TASKS.md #5) picking it up off the real-time pipeline, not a
database poll.

Once matched, fetch either request by id -- pass the *other* rider's id as
`viewer_request_id` to see the post-match reveal (precise location +
contact), or leave it off (or pass your own id) to see the same redacted
view everyone else gets:

```bash
# <request-a-id> / <request-b-id> are the "id" fields from the two POST
# responses above.
curl "http://127.0.0.1:8000/requests/<request-a-id>?viewer_request_id=<request-b-id>"  # full view
curl "http://127.0.0.1:8000/requests/<request-a-id>"                                    # redacted view
```

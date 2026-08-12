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

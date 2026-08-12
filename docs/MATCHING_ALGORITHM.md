# Matching Algorithm Design

## Request schema

```
RideRequest
  id: uuid
  rider_id: str
  origin: {lat, lng}
  destination: {lat, lng}
  earliest_departure: datetime
  latest_departure: datetime
  seats_needed: int
  posted_at: datetime
```

Real WhatsApp messages are unstructured ("leaving IAD 9ish need 2 seats to
Fairfax"). Parsing that into this schema is its own small NLP/regex task —
tracked separately in TASKS.md, kept decoupled from the matching core so the
engine can be developed and tested against clean structured data first.

## Why this isn't "just a database query"

A naive approach filters rows by origin-city and destination-city equality.
That fails constantly: it misses "close enough" origins (two people 1.2mi
apart who'd happily walk to a shared pickup), ignores whether two routes
actually run in a compatible direction (someone going Herndon→Reston is not
a match for someone going Reston→Herndon even if both mention both towns),
and treats time as exact-match instead of a window. The interesting part of
this project is encoding those three dimensions — space, direction, and
time — into a real scoring function.

## Matching pipeline

**1. Spatial bucketing (candidate reduction).**
Index requests with [H3](https://h3geo.org/) hexagonal cells (resolution
~8, ~460m edge) on both origin and destination. Only requests sharing or
neighboring an origin cell AND sharing or neighboring a destination cell
become match candidates. This turns an O(n²) all-pairs comparison into a
hash-bucket lookup — the part of this project that's a legitimate systems
answer to "how does this scale past 1,000 users."

**2. Compatibility scoring.**
For each candidate pair/group, score:
- **Spatial fit**: haversine distance between origins + between
  destinations, normalized.
- **Directional fit**: bearing similarity between each request's
  origin→destination vector (cosine similarity of bearings) — this is what
  catches the "opposite direction" false-positive above.
- **Temporal fit**: overlap of `[earliest_departure, latest_departure]`
  windows.
- **Capacity fit**: hard constraint, not scored — group seats_needed must
  fit within a vehicle/trip capacity.

Combine into a single compatibility score (weighted sum to start; each
weight is a named, tunable constant — not a magic number — so the tradeoffs
are explainable).

**3. Grouping.**
Two-phase, because "who rides with whom" for groups >2 is a clustering
problem, not a simple pairing:
- **Baseline (build first)**: greedy — sort candidate pairs by score
  descending, assign greedily while respecting capacity, no backtracking.
  Simple, explainable, O(n log n) after bucketing. Ship this first; it's
  the honest MVP.
- **Upgrade (if time allows)**: pose as a min-cost assignment /
  set-partitioning problem and solve with `scipy.optimize.linear_sum_assignment`
  for pairwise, or a simple local-search improvement pass on top of the
  greedy baseline for groups >2. Framed as "greedy first, then measured
  against an optimal baseline" — that comparison is itself a good interview
  talking point (know the naive answer before reaching for the fancy one).

## Real-time architecture

Requests don't arrive in a batch — they trickle in over the evening. The
demo models this honestly:

- A **simulator** replays a fixed sample dataset (timestamps preserved from
  the source pattern, optionally time-compressed) and publishes each
  request as an event.
- A lightweight **pub/sub layer** (in-process `asyncio.Queue` first;
  Redis pub/sub is a documented "if this needed to scale past one process"
  upgrade, not built speculatively) fans events out to the matching engine.
- The engine performs **incremental matching**: new request → re-run
  bucketing/scoring only against relevant existing unmatched requests
  (its H3 neighborhood), not a full recompute. This is the detail that
  proves "real-time," not polling a database every N seconds.
- Matches are pushed to subscribers over a **WebSocket** as they're found.

## Explicitly deferred (not tonight, maybe never for the demo)

- Real routing/ETA (would call a routing API — costs money, needs real
  road-network data, not needed to demonstrate the matching logic).
- Multi-stop pooled routes / vehicle routing problem (VRP) proper — the
  current scope is "who should ride together," not "what's the optimal
  route for the driver." Worth naming as a "next step" in interviews, not
  worth building now.

# Task Backlog

Rules for how this file is used (read this before running any task, human or
scheduled agent):

- Work **one task at a time**, top to bottom, unless told otherwise.
- Every task branches off `main` into `nightly` (or continues on it),
  never commits to `main` directly.
- A task is only "done" when its acceptance criteria pass — run the tests,
  don't just write code and stop.
- If a task turns out to be bigger than it looks, stop, commit what works,
  and leave a note under the task instead of pushing through scope creep.
- Move a finished task to the "Done" section at the bottom with the commit
  hash, so the log doubles as a changelog.
- **I'm deliberately capping automated runs to a small number of commits
  per invocation** — I want to actually learn from this, not just watch
  code appear, so the morning run makes at most 2 commits and the evening
  run at most 1. Small enough that I can read the whole diff. Stop at the
  cap even if more work is cleanly ready; pick it up next run. This is a
  hard ceiling, not a target to hit regardless of readiness — 0 or 1
  commits in a run because nothing else was safely done yet is fine, not
  a shortfall.
- I merge `nightly` into `main` myself, by hand, after I've reviewed it —
  automated runs never do this.

Phase 2 items (multi-region, payments, SMS/OTP identity, moderation
tooling) are intentionally not listed here — see SCOPE.md's "Phase 2"
section. Don't pull them forward without an explicit scope conversation.

## Up next

### 6. Structured intake + privacy-safe read API
- `POST /requests`: accepts the structured form fields (task 1), not raw
  text — this replaces what would otherwise be a WhatsApp-message-parsing
  task; there isn't one, by design.
- `GET /requests`: returns open requests with **coarse location + fuzzed
  time only** — this is the response-shaping step flagged in task 1.
  Write a test that posts a request with a precise address-level
  location and asserts the precise value never appears in this
  endpoint's response.
- `WS /matches`: streams match events, wired to the engine from task 5.
- **Acceptance**: automated tests using FastAPI's `TestClient` for both
  HTTP routes, including the privacy-shaping test above; manual
  curl/websocket smoke test documented in README.

### 7. Post-match reveal
- Once two requests are matched, both parties' precise location and
  `contact` become visible **to each other only** (e.g. `GET
  /requests/{id}` returns precise/contact fields when the requester is
  the matched counterpart, coarse/redacted otherwise).
- **Acceptance**: test asserts a non-matched caller gets the redacted
  view and the matched counterpart gets the full view of the same
  request.

### 8. Simulator + minimal live view
- Script that replays the sample dataset with realistic (compressed)
  timing against the running API; a barebones page or CLI subscriber
  that prints matches as they arrive.
- **Acceptance**: running `python backend/simulate.py` against a running
  server produces visible match events during the run, not just at the
  end.

## Done

### 1. Data models + sample dataset (`1329205300f1b225c1393eb17fbc848dca0e1861`)
- `RideRequest` now has a `schedule: OneOffSchedule | RecurringSchedule`
  union (one or the other, never both), `status` (open/matched/expired,
  default open), and a required `contact` field. `Location.coarse_cell()`
  wraps a shared `app/geo.py` H3 helper (resolution 8) so task 2's
  bucketing reuses the same index rather than a second geocoding scheme.
- `app/sample_data.py` seeds 10 invented requests across SCOPE.md's named
  towns, covering one-off/recurring and stranger/group combinations, plus
  an opposite-direction pair and a close-origin pair for task 2's
  bucketing tests.
- Excluding `contact` from pre-match API responses is left to task 6
  (response-shaping), per that task's own acceptance criteria.

### 2. Spatial bucketing (`66bdb57736584d7cfe3e6c2b394490ad5031558e`)
- `app/matching/bucketing.py` builds origin/destination H3 cell indexes
  once (`build_indexes()`) and reuses them for every candidate lookup
  (`candidates_for()` / `candidate_groups()`), so this stays a
  hash-bucket lookup rather than an all-pairs scan. Reuses
  `Location.coarse_cell()` from task 1 -- same H3 index, no second
  geocoding scheme.
- A request is a candidate only if its origin cell AND destination cell
  are both within one hex ring (`NEIGHBOR_RING = 1`) of the query
  request's -- same-or-adjacent, "close enough to share a pickup."
- rider-1 (Fairfax->Aldie) / rider-2 (Aldie->Fairfax) in the sample
  dataset are the opposite-direction fixture: same two towns, opposite
  order, ~15mi apart on each leg, so their origin (and destination)
  cells aren't neighbors and bucketing excludes the pair -- tested in
  `tests/test_bucketing.py`. True same-corridor opposite-direction
  false positives (close origins, opposite bearing) are task 3's
  directional-scoring job, not bucketing's -- bucketing only prunes on
  distance.

### 3. Compatibility scoring (`cbc6655c5d03e476bad0f70a7154733f9692ef28`)
- `app/matching/scoring.py` implements the four dimensions from
  docs/MATCHING_ALGORITHM.md: `spatial_score()` and `directional_score()`
  (haversine distance + bearing cosine similarity, both new in
  `app/geo.py` so the pooling engine has its own copy rather than reaching
  into the separate dispatch module's), `temporal_score()` (window overlap
  normalized by the shorter window), and `capacity_fits()` as a hard
  boolean constraint kept out of the weighted sum, per the doc. Weights
  (`WEIGHT_SPATIAL`/`WEIGHT_DIRECTIONAL`/`WEIGHT_TEMPORAL`) are named
  module constants, not magic numbers.
- `expand_schedule()` is the recurring -> one-off pre-processing step: a
  `RecurringSchedule` becomes one `OneOffSchedule` per weekday in the
  current Monday-Sunday week, so `temporal_score()`/`compatibility_score()`
  only ever see one-off windows, never a recurring pattern directly.
- rider-1/rider-7 (close origin, same Aldie destination, overlapping
  window) score higher via `compatibility_score()` than rider-1/rider-2
  (opposite direction) -- the known-good-vs-known-bad acceptance test.

### 4. Greedy matching engine (`10a92dd`)
- `app/matching/engine.py`'s `MatchingEngine.match_batch()` scores every
  bucketed candidate pair once (bucketing #2 + scoring #3), sorts
  descending, and assigns greedily with no backtracking, per the design
  doc's baseline. Only produces pairs -- `MatchGroup`s of size >2 are the
  doc's explicit "upgrade, if time allows" phase, not built here.
- `DEFAULT_VEHICLE_CAPACITY = 4` is a new named constant standing in for
  "how many people can realistically share one car" -- there's no
  separate driver/vehicle entity in rider-to-rider pooling (that's the
  unrelated dispatch module), so this is my own reasonable default rather
  than something SCOPE.md specifies; worth revisiting if real usage shows
  a different typical party size.
- Added a directional hard cutoff (`MIN_DIRECTIONAL_SCORE = 0.5`,
  alongside `capacity_fits()`) because the weighted `compatibility_score`
  alone wasn't enough to reject a same-cell, opposite-direction pair --
  perfect spatial/temporal scores could otherwise outweigh a directional
  score of 0. Tested with a synthetic close-points-reversed-direction
  fixture in `test_engine.py`, since the sample dataset's real
  opposite-direction pair (rider-1/rider-2) is already excluded at the
  bucketing stage and wouldn't exercise this cutoff.
- A successful match flips both requests' `status` to `matched` in place;
  everything else stays `open` (verified against the full sample dataset).

### 5. Incremental matching + in-process pub/sub (`7f8cb1f`)
- `MatchingEngine.on_new_request()` is match_batch()'s incremental sibling:
  it builds bucketing indexes over just `self._unmatched` (the running
  pool, not every open request) and scores `request` only against its own
  H3 neighborhood within that pool -- "re-run bucketing/scoring only
  against relevant existing unmatched requests," per
  docs/MATCHING_ALGORITHM.md. A match flips both requests' `status` and
  drops the matched candidate from the pool; a non-match adds `request` to
  the pool for the next call. Returns a list of zero or one `MatchGroup`
  (a new request matches at most one existing one) so it keeps
  match_batch()'s return shape.
- Added `submit()`/`run_forever()`, an `asyncio.Queue`-backed pipeline
  (`incoming` in, `matches` out) around `on_new_request()` -- the
  real-time entry/exit points TASKS.md #6's WebSocket and #8's simulator
  will plug into, so neither has to build its own queue wiring.
- Tested with a monkeypatched `compatibility_score` call counter (per this
  task's own acceptance wording: assert on call counts, not just output)
  proving a 5-request pool only gets scored once, not five times, when
  just one request shares the new request's bucket; a two-arrivals test
  (`on_new_request` called twice, matching on the second call); and an
  `asyncio`-driven test exercising `submit()`/`run_forever()` end to end.

_(the dispatch side-module is a separate, already-complete slice; see
backend/app/dispatch/README.md)_

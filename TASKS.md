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

### 3. Compatibility scoring
- Implement scoring functions (spatial, directional, temporal, capacity)
  per docs/MATCHING_ALGORITHM.md, in `backend/app/matching/scoring.py`.
- Recurring requests get expanded to concrete one-off instances (e.g. a
  "weekdays at 9am" request becomes 5 candidate instances for the current
  week) before scoring — scoring itself should only ever see one-off time
  windows, so this stays a pre-processing step, not new scoring logic.
- **Acceptance**: unit tests for each scoring dimension independently,
  plus one test asserting a known-good pair scores higher than a
  known-bad pair, plus one test proving a recurring request expands to
  the expected number of instances and each scores independently.

### 4. Greedy matching engine
- Implement `MatchingEngine.match_batch()` in
  `backend/app/matching/engine.py` using bucketing + scoring + greedy
  assignment.
- A successful match flips both requests' `status` to `matched` (task 1's
  field) — this is the only place `status` transitions away from `open`
  in a batch run.
- **Acceptance**: running the full sample dataset through the engine
  produces a matches list with no capacity violations and no
  opposite-direction false matches; test asserts both, plus asserts
  matched requests' `status` updates correctly.

### 5. Incremental matching + in-process pub/sub
- Add `MatchingEngine.on_new_request()` for incremental (not full-recompute)
  matching, backed by an `asyncio.Queue`.
- **Acceptance**: test simulates requests arriving one at a time and
  asserts matches appear without re-scoring the entire dataset each time
  (assert on call counts, not just output).

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

_(the dispatch side-module is a separate, already-complete slice; see
backend/app/dispatch/README.md)_

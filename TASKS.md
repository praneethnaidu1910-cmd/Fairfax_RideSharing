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

## Up next

### 1. Data models + sample dataset
- Implement `RideRequest`, `Location` in `backend/app/schemas.py` (Pydantic).
- Write `backend/app/sample_data.py`: 30-50 synthetic ride requests modeled
  on realistic Fairfax/Ashburn/Herndon/Chantilly/Reston patterns (invented
  data, not real message content, unless real anonymized examples have been
  provided separately — never hardcode real phone numbers/names).
- **Acceptance**: `pytest backend/tests/test_schemas.py` passes; sample
  data loads and validates against the schema.

### 2. Spatial bucketing
- Implement H3-based bucketing in `backend/app/matching/bucketing.py`
  (use the `h3` package).
- **Acceptance**: given the sample dataset, bucketing returns candidate
  groups that visibly exclude far-apart / opposite-direction requests.
  Test with a fixture pair that should NOT match (e.g. opposite commute
  directions) and assert it's excluded.

### 3. Compatibility scoring
- Implement scoring functions (spatial, directional, temporal, capacity)
  per `docs/MATCHING_ALGORITHM.md`, in `backend/app/matching/scoring.py`.
- **Acceptance**: unit tests for each scoring dimension independently, plus
  one test asserting a known-good pair scores higher than a known-bad pair.

### 4. Greedy matching engine
- Implement `MatchingEngine.match_batch()` in `backend/app/matching/engine.py`
  using bucketing + scoring + greedy assignment.
- **Acceptance**: running the full sample dataset through the engine
  produces a matches list with no capacity violations and no
  opposite-direction false matches; test asserts both.

### 5. Incremental matching + in-process pub/sub
- Add `MatchingEngine.on_new_request()` for incremental (not full-recompute)
  matching, backed by an `asyncio.Queue`.
- **Acceptance**: test simulates requests arriving one at a time and
  asserts matches appear without re-scoring the entire dataset each time
  (assert on call counts, not just output).

### 6. FastAPI + WebSocket layer
- `POST /requests` to submit a request, `WS /matches` to stream match
  events, wire to the engine from task 5.
- **Acceptance**: manual curl/websocket smoke test documented in README;
  automated test using FastAPI's TestClient for the HTTP route at minimum.

### 7. Simulator + minimal live view
- Script that replays the sample dataset with realistic (compressed) timing
  against the running API; a barebones page or CLI subscriber that prints
  matches as they arrive.
- **Acceptance**: running `python backend/simulate.py` against a running
  server produces visible match events during the run, not just at the end.

## Done

_(nothing yet — tonight was scoping + skeleton)_

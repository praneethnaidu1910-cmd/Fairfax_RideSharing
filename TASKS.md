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
- **Anything requiring a real account, billing, or a secret only I have
  (hosting signup, a database connection string, an API key) is off
  limits to automated runs, no exceptions** — task 13 below is explicitly
  marked for this reason. Claude doesn't create accounts or enter payment
  details on my behalf whether I'm watching or not; that step is mine to
  do by hand, in an interactive session.

Phase 2 items (multi-region, payments, SMS/OTP identity, moderation
tooling) are intentionally not listed here — see SCOPE.md's "Phase 2"
section. Don't pull them forward without an explicit scope conversation.

The original 8-task backlog (matching engine + API) is done -- see
"Done" below. What's up next is what it takes to get from "backend
that works" to "something a real person can actually open and use."

## Up next

### 13. Deployment (manual only -- not for automated runs)
- Get the API, frontend, and database onto a real public URL. This does
  **not** go through the scheduled routines -- see the rule above. It
  needs a hosting account and billing setup, which is mine to do by
  hand; once that account exists, an interactive session can configure
  the app against whatever connection details/env vars I hand over.
- **Acceptance**: the app is reachable at a real URL from a phone or
  laptop that isn't the machine running it.

### 19. Legal research memo: ride-cost-splitting vs. carpooling in Virginia (manual/research only -- not for automated code-writing runs)
- SCOPE.md names this open question explicitly and says it's "worth
  actually researching before this goes live... not something to
  resolve by assumption in this file." This is a legal-risk judgment
  call, not a coding task -- flagging it the same way task 13 is
  flagged, so an automated run doesn't try to resolve it by writing code
  or asserting a legal conclusion on my behalf.
- **Acceptance**: this is mine to look into by hand (with a real
  lawyer's input if it comes to that), not something a scheduled run
  should check off.

## Done

### 37. Reject a timezone-aware departure datetime/time instead of 500ing on it
- Not a numbered "Up next" item -- "Up next" only has tasks 13/19 on it and
  both are manual-only, so this evening run went looking for a real bug
  the same way the last several runs did, and found one in
  `app/schemas.py` this time: a gap between what Pydantic will happily
  parse and what the rest of this codebase actually assumes about every
  datetime it touches.
- Every datetime this app generates itself is naive: `datetime.utcnow()`
  (`scoring.is_expired()`, `RideRequest.posted_at`/`status_changed_at`
  defaults), and the `DateTime(timezone=False)` columns `app/models.py`
  persists to. But `OneOffSchedule.earliest_departure`/`latest_departure`
  and `RecurringSchedule`'s bare `earliest_departure_time`/
  `latest_departure_time` are client input, and Pydantic parses a
  perfectly normal-looking ISO 8601 string with an offset ("2026-01-01T14
  :00:00-05:00") or a "Z" suffix into a *timezone-aware* value without
  complaint. Comparing a naive and an aware datetime (or `time`) doesn't
  raise a clean `ValueError` Pydantic can turn into a 422 -- it's a bare
  `TypeError`, so it crashes straight through. Confirmed this was real,
  not theoretical, with a live `TestClient` before writing any fix: `POST
  /requests` with a tz-aware `earliest_departure` 500'd inside
  `OneOffSchedule`'s own "latest must not be before earliest" check (both
  fields tz-aware, so the comparison itself raised); a recurring schedule
  with *one* field tz-aware and the other naive 500'd the same way one
  level down, in `RecurringSchedule`'s own window check. Nothing about
  this needs a browser -- the web form's `datetime-local`/`time` inputs
  never carry a timezone, but nothing stops a non-browser API client (a
  future mobile client, or just a well-meaning `curl` with `date
  --iso-8601=seconds`, which includes an offset by default) from sending
  one, and SCOPE.md never says this API is browser-only.
- Fix: both schedules' existing `@model_validator(mode="after")` checks
  now reject a tz-aware value for any of their datetime/time fields
  *before* comparing them against each other, with a clear `ValueError`
  (a clean 422) instead of letting the comparison itself raise. Same
  "reject bad client input at the one place it enters this shape" pattern
  as `Location`'s lat/lng range check and `NonBlankStr` -- not trying to
  guess the client's intended timezone and silently reinterpret it as
  naive UTC, which would be a real product decision (what timezone does a
  naive datetime even mean in this app?) this fix doesn't need to make to
  just stop the crash.
- Tests: `tests/test_schemas.py` adds
  `test_one_off_schedule_rejects_timezone_aware_datetimes` (both fields
  tz-aware, and the "Z"-suffix spelling) and
  `test_recurring_schedule_rejects_timezone_aware_times` (one field
  tz-aware, one naive -- the exact mismatch that crashed one level deeper
  than the all-aware case). `tests/test_requests_api.py` adds the
  HTTP-level reproduction, `test_create_request_rejects_timezone_aware_departure_times`
  -- the exact tz-aware `POST /requests` payload above now `422`s. Ran all
  three against the pre-fix code first (temporarily stashing just
  `app/schemas.py`) to confirm they actually fail there -- a real `500`
  and two uncaught `TypeError`s, not just that they pass now. Full suite:
  164 tests, up from 161, all green.

### 36. Fix temporal_score() scoring a precise departure instant as zero overlap with a window that contains it
- Not a numbered "Up next" item -- "Up next" only has tasks 13/19 on it and
  both are manual-only, so this morning run went looking for a real bug
  the same way the last several runs did, and found one in
  `app/matching/scoring.py`'s `temporal_score()` -- the exact function
  task 33 already added a hard cutoff around, just a different edge in the
  same formula.
- `OneOffSchedule`'s own validator only requires `latest_departure >=
  earliest_departure`, so `latest_departure == earliest_departure` -- a
  precise single-instant "window," not a range -- is a real, reachable
  input: nothing in `/new`'s two separate datetime-local fields or in
  `RideRequestCreate` stops a rider from typing the same value into both
  (plausible for anyone who thinks of their trip as "leaving at exactly
  9am," not as a flexible window, same instinct SCOPE.md's own real
  message samples show -- "leaving IAD 9ish"). Confirmed this was real,
  not theoretical, with a live script before writing any fix: a precise
  2pm request and a 1:45-2:15pm request, identical origin/destination,
  scored `temporal_score() == 0.0` -- the exact same number two requests
  13 hours apart would score -- because `overlap_seconds` collapses to
  exactly 0 whenever either window has zero width, regardless of whether
  that instant falls squarely inside the other window or nowhere near it.
  Fed through the real engine, `on_new_request()` never matched the two
  arrivals (`MIN_TEMPORAL_SCORE`'s hard cutoff, task 33, correctly rejects
  anything scoring `<= 0.0` -- it just had no way to tell "truly disjoint"
  apart from "one side is a single instant the other side's window already
  covers"), and both sat in the pool forever with nothing anywhere
  surfacing that the engine was treating a perfect time match as if it
  were the worst possible one.
- Fix: `temporal_score()` now only treats a *strictly negative*
  `overlap_seconds` as "no overlap at all" (genuinely disjoint windows,
  same as before). An exact zero with at least one zero-width window means
  that window's one and only acceptable instant is covered by the overlap
  -- the best possible temporal fit for it, not the worst -- so that case
  now scores `1.0` instead of falling through to a `0 / shortest_window`
  division. This is the formula's own natural limit as a window's width
  shrinks toward zero while staying fully contained in the other's range,
  not a new, separately-invented number. Deliberately narrow: two normal,
  positive-width windows that merely touch at a shared boundary instant
  (not one side being zero-width) still score 0, exactly as before --
  that's a different case this fix doesn't touch, since nothing forces a
  non-arbitrary answer for it the way the zero-width case's own containment
  does.
- Tests: `tests/test_scoring.py` adds
  `test_temporal_score_precise_instant_contained_in_a_window_is_a_perfect_match`
  (a precise instant inside a real window scores `1.0`, two identical
  precise instants score `1.0`, a precise instant outside a window still
  scores `0.0`) and
  `test_temporal_score_two_normal_windows_merely_touching_still_scores_zero`
  (the narrower boundary-touch case this fix leaves alone).
  `tests/test_engine.py` adds
  `test_on_new_request_matches_a_precise_departure_time_inside_the_others_window`,
  the real-engine reproduction above -- two arrivals, same route, one
  precise and one flexible, now actually match. Ran both new scoring
  assertions and the engine test against the pre-fix code first to confirm
  they actually fail there (`0.0`/no match, not `1.0`/matched), not just
  that they pass now. Full suite: 161 tests, up from 158, all green.

### 35. Stop cancel from silently succeeding (and resetting the retention clock) on an already-expired request
- Not a numbered "Up next" item -- "Up next" only has tasks 13/19 on it and
  both are manual-only, so this evening run went looking for a real bug
  the same way the last several runs did, and found one in `cancel_request()`
  that's been sitting right next to its own docstring this whole time.
- `cancel_request()`'s docstring has said since task 15 that "a MATCHED
  request... an EXPIRED one... and a second cancel on an already-CANCELLED
  one" should all 409, but the actual check was
  `target.status != RequestStatus.OPEN` -- the *raw stored* status. Task
  14's whole point is that an expired one-off request's stored status
  never actually becomes `expired`; that's a read-time computation
  (`to_public()`/`is_expired()`) that nothing ever writes back, so the
  stored value stays `open` forever. That meant the EXPIRED case in the
  docstring was never real: cancelling a request GET already reports as
  `expired` sailed through with a `200` and flipped it to `cancelled`
  instead of 409ing. Confirmed this was real, not theoretical, with a live
  `TestClient` before writing any fix: posted a one-off request with a
  departure window 2 hours in the past (so `GET` already reports
  `"status": "expired"`), then called the real cancel endpoint against it
  -- got back a `200` and `"status": "cancelled"`, not the `409` its own
  docstring describes.
- Worse than just a wrong status code: `cancel_request()` stamps
  `status_changed_at = datetime.utcnow()` on every successful cancel, and
  `app/retention.py`'s `terminal_at()` reads that same field to decide when
  a *cancelled* request became retention-eligible -- but for an
  already-expired request, the *correct* terminal moment is the window's
  own `latest_departure` (expired, not cancelled, is what actually
  happened to it; see `terminal_at()`'s own `OPEN`+`is_expired()` branch).
  So this bug didn't just mislabel the request -- it silently pushed the
  30-day anonymization clock (TASKS.md #17) out to "now," needlessly
  extending how long its precise pickup/dropoff and real contact info sat
  around in Postgres unredacted, for any id a caller could guess or still
  had bookmarked after the window passed. No auth gates `POST
  /requests/{id}/cancel` (SCOPE.md's open-join model), so this wasn't just
  a self-inflicted footgun for the original poster either.
- Fix: compare against `to_public(target).status` -- the same *computed*
  status `GET /requests[/{id}]` already reports, reusing task 32's own
  pattern of not duplicating `is_expired()` logic a second time -- instead
  of the raw stored value. An `open`-and-not-expired request is unaffected;
  `matched`/`cancelled` were already correctly rejected before this fix (their
  stored and computed status are the same thing) and still are; `expired`
  now actually 409s like the docstring always said, and the 409 message
  itself now says `'expired'` instead of the misleading `'open'` it would
  have said had the raw value been used for the message too.
- Tests: new
  `tests/test_requests_api.py::test_cancel_an_expired_request_returns_409`
  reproduces the exact scenario above (a past-window one-off, `GET`
  reporting `expired`, then a real cancel call) and asserts `409`, the
  `'expired'` detail message, and that a follow-up `GET` still reports
  `expired`, not `cancelled`. Ran it against the pre-fix code first
  (temporarily stashing just `app/router.py`) to confirm it actually fails
  there -- a real `200`/`cancelled` came back, not just that it passes now.
  Full suite: 158 tests, up from 157, all green.

### 34. Fix bucketing's candidate radius silently undercutting scoring's own 5-mile "close enough to share a pickup" threshold
- Not a numbered "Up next" item -- "Up next" only has tasks 13/19 on it and
  both are manual-only, so this morning run went looking for a real bug the
  same way the last several runs did, and found one in
  `app/matching/bucketing.py` this time: a mismatch between the candidate-
  reduction step and the scoring step it's supposed to feed, not a bug in
  either one taken alone.
- `scoring.py`'s `MAX_PICKUP_DISTANCE_MILES = 5.0` is the threshold
  `spatial_score()` actually scores against -- its own comment cites
  SCOPE.md's own example almost verbatim: "two people 1.2mi apart who'd
  happily walk to a shared pickup." But `bucketing.py`'s
  `candidates_for()` runs *before* any scoring happens, and its old
  `NEIGHBOR_RING = 1` ("same-or-adjacent hex ring") only guarantees real-
  world coverage of about half a mile at `COARSE_RESOLUTION` (H3
  resolution 8) -- confirmed by walking every 5-degree bearing out from a
  Fairfax-area point and binary-searching exactly where ring membership
  flips. A pair 1.2 miles apart never became a candidate at all, so
  `spatial_score()`'s 5-mile threshold was silently dead code for most of
  its own range: `candidates_for()` threw the pair out before scoring ever
  ran. Confirmed this was real, not theoretical, with a live script before
  writing any fix: two one-off riders built from SCOPE.md's own example
  (same destination, same departure window, origin 1.2mi apart --
  `spatial_score` 0.88, `directional_score` 0.999, a textbook match on
  every dimension `scoring.py` weighs) fed through the real
  `on_new_request()` one at a time, and the second arrival came back `[]`
  -- no match, not pooled against each other at all, with nothing
  anywhere surfacing that bucketing and scoring disagreed about what
  "close enough" means by almost an order of magnitude. The existing
  "1.2mi apart" fixture in `app/sample_data.py` (rider-1/rider-7, already
  used by several tests) turned out to actually be ~0.33mi apart in real
  coordinates despite its own comment's claim -- comfortably inside the
  old too-narrow ring, which is exactly why no existing test ever caught
  this: the fixture's comment described the boundary case it meant to
  represent, but the actual numbers never exercised it. Left that fixture
  alone rather than widening it to a real 1.2mi, since its coordinates are
  shared by several other test files beyond this task's scope
  (`test_live_matches.py`, `test_requests_api.py`,
  `app/dispatch/sample_drivers.py` all reuse the same point) and changing
  it isn't needed to close this gap -- new fixtures below do that instead.
- Fix: `NEIGHBOR_RING` is now `12`, the smallest ring confirmed (same
  bearing-walk method as the reproduction above) to guarantee real-world
  coverage of `MAX_PICKUP_DISTANCE_MILES` in every direction at
  `COARSE_RESOLUTION`, with a little margin to spare (worst-case ~5.66mi
  covered against the 5.0mi requirement) -- a k-ring isn't a circle, so
  the hex grid's worst-case direction covers meaningfully less real-world
  distance per k than its best-case direction, ruling out a simple
  "distance / edge length" formula. Ties the two constants together by
  comment and by a dedicated coverage test (below) rather than leaving
  them independently hand-tuned and silently driftable the way they
  already had drifted once.
- Tests: `tests/test_bucketing.py` adds
  `test_bucketing_includes_scopes_own_1_2_mile_shared_pickup_example`
  (builds the exact 1.2mi reproduction above and asserts
  `candidate_groups()` now includes each rider in the other's candidate
  set) and
  `test_neighbor_ring_covers_max_pickup_distance_in_every_direction` (the
  general guarantee -- walks a point exactly `MAX_PICKUP_DISTANCE_MILES`
  away at every 15-degree bearing from a Fairfax-area origin and asserts
  it's still inside the `NEIGHBOR_RING`-ring, so a future change to
  `NEIGHBOR_RING`, `MAX_PICKUP_DISTANCE_MILES`, or `COARSE_RESOLUTION`
  that breaks this relationship again gets caught here instead of
  silently reintroducing the same gap). Ran both against the pre-fix
  `NEIGHBOR_RING = 1` first to confirm they actually fail there -- they
  did, on both tests -- not just that they pass now. Also reran the full
  suite afterward to confirm the wider ring doesn't change any existing
  test's outcome (it doesn't -- the sample dataset's other "far apart"
  negative fixtures are all well beyond the new ring's ~5.6mi reach too).
  Full suite: 157 tests, up from 155, all green.

### 33. Add a hard cutoff so a pair with zero departure-window overlap can't match on spatial/directional fit alone
- Not a numbered "Up next" item -- same as the last many entries here,
  "Up next" only has tasks 13/19 on it and both are manual-only, so this
  evening run went looking for a real bug instead of stopping, and found
  one in `app/matching/engine.py` right next to the directional cutoff
  task 4 added back when this engine was first built.
- `match_batch()`/`on_new_request()` already have a hard cutoff on
  `directional_score` (`MIN_DIRECTIONAL_SCORE`, task 4's own note: "the
  weighted `compatibility_score` alone wasn't enough to reject a same-cell,
  opposite-direction pair") and a hard constraint on `capacity_fits()` --
  but nothing analogous existed for `temporal_score`, even though
  docs/MATCHING_ALGORITHM.md names time overlap as one of the same three
  real matching dimensions (space, direction, time) spatial/directional
  already get hard cutoffs for. Confirmed this was real, not theoretical,
  with a live script before writing any fix: two one-off riders, same
  corridor, close origins, departing **13 hours apart on the same day**
  (7am and 8pm) -- `temporal_score()` correctly computed `0.0` for that
  pair, but `compatibility_score()`'s `WEIGHT_SPATIAL + WEIGHT_DIRECTIONAL`
  (0.75 combined) was enough on its own to win a greedy match slot anyway.
  The resulting `MatchGroup.reason` (task 20's own explain_match() output)
  literally read `"...0min window overlap, capacity fits"` -- the engine
  was matching two riders it could plainly see don't overlap in time at
  all, the exact "perfect spatial/temporal... could otherwise outweigh"
  failure mode task 4's own note already describes for direction, just
  never closed for time.
- Fix: new `MIN_TEMPORAL_SCORE = 0.0` hard cutoff, same pattern as
  `MIN_DIRECTIONAL_SCORE` -- a window pair now has to clear
  `temporal_score(window_a, window_b) > MIN_TEMPORAL_SCORE` (i.e. the two
  windows have to actually overlap at all) before `compatibility_score()`
  ever gets computed for it, in both `match_batch()`'s per-pair window loop
  and `on_new_request()`'s. Deliberately the narrowest version of this fix
  -- requiring *some* real overlap, not picking an arbitrary minimum
  fraction of overlap, since the weighted sum already handles "how good is
  a small-but-real overlap" on its own; only the "literally zero overlap"
  case needed a hard floor, the same way only "literally opposite
  direction" needed one for bearing.
- Separate, bigger gap I found right next to this one but am **not**
  fixing here, flagging instead since it's a real design question, not a
  pure bug: `expand_schedule()` always expands a `RecurringSchedule` to
  "the Monday-Sunday week containing `date.today()`" with no way to target
  a different week. That means a recurring Monday rider can only ever be
  scored against *this calendar week's* Monday occurrence -- so a one-off
  request dated any week other than the current one (e.g. "next Monday," 7
  days out) gets compared against a recurring rider's stale/already-passed
  occurrence from this week instead of the actual future date they'd really
  share, scoring `0min window overlap` and (correctly, now) never matching,
  even though the two riders really would be compatible on the date that
  actually matters. Fixing this needs a real decision -- e.g. should
  `on_new_request()`/`match_batch()` expand a recurring schedule across
  several weeks ahead, or key off the *incoming* one-off request's own
  date instead of `date.today()` -- not something to guess at while also
  touching the exact-zero-overlap fix above in the same pass.
- Tests: `tests/test_engine.py` adds
  `test_match_batch_excludes_pair_with_no_window_overlap` and
  `test_on_new_request_does_not_match_a_candidate_with_no_window_overlap`,
  both using the same 13-hours-apart-same-day fixture the manual script
  above used. Ran both against the pre-fix code first to confirm they
  actually fail there (a real `MatchGroup` comes back instead of `[]`) --
  they did, on both tests -- not just that they pass now. Full suite: 155
  tests, up from 153, all green.

### 32. Stop `/mine/{id}` from telling a cancelled/expired poster their request is still "waiting for a match"
- Not a numbered "Up next" item -- "Up next" only has tasks 13/19 on it and
  both are manual-only, so this morning run went looking for a real bug the
  same way the last several runs did, and found one in the web frontend
  this time instead of the matching engine/race-condition territory the
  last several entries all lived in.
- `GET /mine/{request_id}` (`app/web.py`) only ever passed the template a
  `reveal` (the matched counterpart, or `None`) -- never the request's own
  `status`. `mine.html`'s `{% else %}` branch, meant for "still open, no
  match yet," was the *only* non-reveal branch, so a cancelled request
  (TASKS.md #15's `POST /requests/{id}/cancel`) or an expired one (TASKS.md
  #14) rendered the exact same "Waiting for a match... this page updates
  itself, no need to reload" message as a genuinely still-open one, and
  still loaded `live.js` to open a WebSocket that can never receive a match
  for either. Confirmed this was real, not theoretical, with a live
  `TestClient` before writing any fix: posted a request, cancelled it
  through the real cancel endpoint, then reloaded `/mine/<id>` -- "Waiting
  for a match" was still right there, with nothing on the page telling the
  poster their own cancel had actually gone through.
- Fix: `my_request_status()` now also passes `to_public(mine).status.value`
  -- the same computed status `GET /requests` already reports (so
  "expired" means the same thing here it means there, no duplicated
  `is_expired()` logic) -- and `mine.html` gets two new branches ahead of
  the fallback: `cancelled` and `expired` each get their own plain message,
  neither one loads `live.js` or opens a pointless WebSocket, and the
  original "waiting" branch is now reached only for a genuinely still-open
  request.
- Tests: `tests/test_live_matches.py` adds
  `test_mine_page_shows_cancelled_not_still_waiting_after_cancel` and
  `test_mine_page_shows_expired_not_still_waiting_once_window_passes`. Ran
  both against the pre-fix code first (temporarily stashing just
  `app/web.py`/`mine.html`) to confirm they actually fail there -- they
  did, on the exact "Waiting for a match" text the fix removes -- not just
  that they pass now. Full suite: 153 tests, up from 151, all green.

### 31. Stop on_new_request() from reverting a cancel of the *incoming* request itself, mid-scoring
- Not a numbered "Up next" item -- "Up next" only has tasks 13/19 on it and
  both are manual-only, so this evening run went looking for a real bug the
  same way the last several runs did, and found the third leg of a triangle
  the last two runs already closed two sides of. Task 28 (this morning, two
  runs ago) covers a request cancelled while still sitting in `incoming`,
  before `on_new_request()` ever sees it. Task 29 (last evening) covers an
  already-pooled candidate getting cancelled *while* `on_new_request()` is
  mid-scoring it against a new incoming request. Neither covers the
  remaining case: the *incoming* request itself getting cancelled by its
  own poster during that same scoring window -- it's not in `incoming`
  anymore (already dequeued) and not in `self._unmatched` yet (not pooled
  until/unless no match is found), so neither task 28's nor task 29's fix,
  nor `remove_from_pool()`, has anything to grab onto for it.
- `on_new_request()` already rechecks `best_candidate`'s current store
  status right before committing a match (task 29's fix), but never
  rechecked `request`'s own status the same way -- so a cancel racing the
  *other* half of the pair sailed straight through untouched. Confirmed
  this was real, not theoretical, with the same kind of script task 29's
  own entry describes: pause `on_new_request()` mid-scoring (monkeypatched
  `compatibility_score`), run the real `cancel_request()` sequence against
  the *incoming* request (not the candidate) from another thread in that
  gap, then let scoring finish -- without a fix, the incoming request's
  stored status came back `MATCHED`, silently overwriting the `CANCELLED`
  its poster already got a `200` for, with its location/contact revealed
  to a stranger it explicitly tried to withdraw from matching before the
  cancel had even made it to disk.
- Fix: a second recheck, right after `best_candidate`'s, re-reads
  `request`'s own current status from the store (when one is configured)
  before touching anything. If it's no longer `OPEN`, `on_new_request()`
  returns `[]` without matching *and* without pooling it into
  `self._unmatched` -- a cancelled request has nothing left to pool for.
  `best_candidate` is left exactly where it was (still in the pool,
  un-mutated), since it's still a perfectly good open request for whatever
  arrives next.
- Tests: new
  `tests/test_engine.py::test_on_new_request_does_not_revert_a_cancel_of_the_incoming_request_itself`
  mirrors task 29's own test almost exactly -- same pausing-scorer trick,
  same real `cancel_request()` sequence -- just run against the incoming
  request instead of the candidate. Ran it against the pre-fix code first
  to confirm it actually fails there (`matches == []` assertion fails
  because a real match came back), not just that it passes now. Full
  suite: 151 tests, up from 150, all green.

### 30. Fix a race in the geocoding rate limiter that let concurrent callers skip the 1-request/second spacing
- Not a numbered "Up next" item -- "Up next" only has tasks 13/19 on it and
  both are manual-only, so this morning run went looking for a real bug the
  same way the last several runs did, this time in `app/geocoding.py`,
  which none of the recent bug-hunting passes had touched yet.
- `GET /geocode` (`app/router.py`) is a plain sync route, which Starlette
  dispatches to a threadpool worker, not a single event loop -- two riders
  blurring a pickup/destination field at close to the same moment (both
  tabs on `/new`, task 11) really can call `_wait_for_rate_limit()` from
  two different threads at once. The old function read the module-level
  `_last_request_at`, decided how long to sleep, slept, then wrote
  `_last_request_at` back -- a classic check-then-act race with no lock
  around any of it, so two threads doing this concurrently both read the
  same stale value, both compute the same "elapsed," and both proceed (or
  both sleep the same amount) without ever seeing each other's in-flight
  wait. Confirmed this was real, not theoretical, with a script before
  writing any fix: five threads released at once via a `threading.Barrier`,
  each calling the real `_wait_for_rate_limit()` -- all five landed their
  actual "requests" within about 0.3ms of each other instead of
  `MIN_SECONDS_BETWEEN_REQUESTS` apart, the exact spacing this function
  exists to guarantee against Nominatim's 1-request/second usage policy.
- Fix: a module-level `threading.Lock` (`_rate_limit_lock`) now wraps the
  whole read-sleep-write sequence in `_wait_for_rate_limit()`, so two
  concurrent callers are forced to actually take turns -- the second one
  blocks on the lock until the first finishes its sleep and records its
  call time, then re-reads a now-fresh `_last_request_at` and sleeps the
  right amount itself, instead of racing off the same stale snapshot.
- Tests: new
  `tests/test_geocoding.py::test_rate_limit_keeps_concurrent_callers_spaced_out_too`
  reproduces the exact scenario above (five threads, a barrier, a shrunk
  `MIN_SECONDS_BETWEEN_REQUESTS` so the test stays fast) and asserts every
  consecutive pair of actual call times is at least that far apart. Ran it
  against the pre-fix code first (by temporarily reverting just
  `app/geocoding.py`) to confirm it reliably fails there -- it did, on
  every one of several runs -- and reliably passes with the fix, on every
  one of several runs, before trusting it as a real regression test and
  not a flaky one. Full suite: 150 tests, up from 149, all green.

### 29. Stop a pool-sitting request's cancel from getting silently reverted by a match that's already mid-flight
- Not a numbered "Up next" item -- "Up next" only has tasks 13/19 on it and
  both are manual-only, so this evening run went looking for a real bug the
  same way the last several runs did, and found a close cousin of the race
  task 28 (this morning) just closed: same cancel-vs-match race, but the
  *other* side of it.
- Task 28 covered a request still sitting in `incoming`, queued by
  `submit()` but not yet drained by `run_forever()`, getting cancelled out
  from under it. This is the other window: a request already sitting in
  `self._unmatched` (pooled, a real match candidate for whatever arrives
  next) getting cancelled *while* `on_new_request()` is in the middle of
  scoring it as the best candidate for a brand-new incoming request.
  `POST /requests/{id}/cancel`'s `cancel_request()` (`app/router.py`) is a
  plain sync `def`, which Starlette dispatches to a threadpool worker, not
  the event loop `on_new_request()` runs on -- so the two really can run at
  the same time, not just interleave cooperatively. First suspected this
  reading the router/engine code side by side; ruled out the "two threads
  mutating `self._unmatched` at once" angle with an actual multi-thousand-
  trial stress script first (CPython's list iterator is live, not a
  snapshot, so a plain append/filter-and-reassign pair turned out *not* to
  lose data the way I first guessed), then found the *logical* race was
  real: wrote a script that pauses `on_new_request()` mid-scoring (via a
  monkeypatched `compatibility_score`, which releases the GIL on every
  call anyway) with a real, store-backed cancel running against its only
  candidate in the gap, then lets scoring finish -- without a fix, the
  candidate's own DB row came back `MATCHED` (reverting the cancel a caller
  already got a `200` for) and `self._unmatched.remove(best_candidate)`
  raised `ValueError` right after (caught by task 25's `run_forever()`
  guard in production, so the pipeline survives, but silently -- the match
  event never gets published, and nothing tells anyone the DB now
  disagrees with the cancel that just happened). Worse than just a
  dropped event: since `store.save()` runs *before* the failing
  `self._unmatched.remove()`, the DB write already landed -- a second
  rider's own page (`app/web.py`'s `/mine/{id}`) reading straight from the
  store afterward would show a reveal naming the cancelled rider's real
  contact/location, even though that rider thinks they successfully
  withdrew.
- Fix: `on_new_request()` now re-reads `best_candidate`'s current status
  from the store (when one is configured) right after scoring decides on
  it, before touching anything -- mirrors the exact recheck task 28 added
  to `run_forever()`, just on the other request in the pair. If the store
  says `best_candidate` is no longer `OPEN`, it's dropped from
  `self._unmatched` (it was never going to be matchable anyway) and
  `request` is treated as a non-match this round -- pooled for the next
  arrival, same as any other no-candidate-found case, rather than trying
  to retry against whatever's left in the same pass.
- Tests: new
  `tests/test_engine.py::test_on_new_request_does_not_revert_a_cancel_of_its_own_best_candidate`
  forces the exact interleaving deterministically (no sleeps, no
  probabilistic retries) with a monkeypatched `compatibility_score` plus
  two `threading.Event`s: pause scoring, run the real cancel sequence
  against the pooled candidate from another thread, release, assert no
  exception, the candidate stays `CANCELLED` with no `matched_with`, and
  the incoming request ends up pooled rather than matched. Ran this test
  against the pre-fix code first to confirm it actually fails there (the
  same `ValueError` the manual script hit), not just that it passes now.
  Full suite: 149 tests, up from 148, all green.

### 28. Stop a request cancelled while still queued from getting silently matched anyway
- Not a numbered "Up next" item -- "Up next" only has tasks 13/19 on it and
  both are manual-only, so this morning run went looking for a real bug
  the same way the last several runs did, and found one right next to the
  one task 25 closed in `run_forever()`.
- Task 25 made the matching pipeline survive one bad request; this is a
  different bug in the same loop. `remove_from_pool()` (task 15's cancel
  path) only drops a request from `self._unmatched` -- it can't do
  anything about a request still sitting in `incoming`, queued by
  `submit()` but not yet drained by `run_forever()`. That window is real:
  `POST /requests` calls `engine.submit()` and returns immediately,
  without waiting for the background worker to actually process the
  item. `POST /requests/{id}/cancel` (`app/router.py`) fetches a *fresh*
  `RideRequest` from the store (`store.get()` always builds a new
  instance), flips that copy to `cancelled`, and saves it -- but the
  object still sitting in `incoming` is a different Python instance
  entirely, whose in-memory `.status` never left `open`.
  `remove_from_pool()` no-ops for it since it was never pooled, so when
  `run_forever()` finally reaches it, `on_new_request()` happily matches
  it against someone else and `store.save()`s it right back to `matched`
  -- silently overwriting the `cancelled` status the poster had already
  gotten back a `200` for, and revealing their location/contact to a
  stranger they'd explicitly tried to withdraw from. Confirmed this was
  real, not theoretical, with a script that submits a request, cancels it
  the same way the real endpoint does (fresh copy from the store, not the
  queued object), submits a second compatible one, then lets
  `run_forever()` run -- the cancelled request came back `matched` every
  time before the fix.
- Fix: `run_forever()` now re-checks the request's *current* status in
  the store (when one is configured) the moment it dequeues it from
  `incoming`, before calling `on_new_request()` at all -- if the store
  says it's no longer `open` (cancelled, or anything else), it's skipped
  outright instead of being pooled or matched. Scoped to `run_forever()`
  itself rather than `on_new_request()`, since the gap is specifically
  about trusting a possibly-stale queued object over the store's live
  state, not about `on_new_request()`'s own logic (its existing tests
  construct it without a store and still rely on the passed-in object's
  status being authoritative, which is still true for every caller that
  isn't this one race).
- Tests: new
  `tests/test_engine.py::test_run_forever_does_not_match_a_request_cancelled_while_still_queued`
  reproduces the race directly against a real store/engine pair (submit,
  cancel via a fresh store copy the way the endpoint does, submit a
  second compatible request, let the worker drain both) and asserts the
  cancelled request stays `cancelled` with no `matched_with`, and the
  other request stays `open` rather than getting matched to a
  ghost. Ran it against the pre-fix code first to confirm it actually
  fails there (`cancelled` != `matched`), not just that it passes now.
  Full suite: 148 tests, up from 147, all green.

### 27. Reject a whitespace-only rider_id/contact/report-reason too, not just the empty string
- Not a numbered "Up next" item -- this evening run went looking for a
  real bug the same way the last several runs did, since "Up next" only
  has tasks 13/19 on it and both are manual-only, and found a gap right
  next to the one this morning's run (task 26) just closed.
- Task 26's `Field(min_length=1)` fix checks string *length*, not
  content -- a whitespace-only value like `"   "` has length 3, so it
  sailed straight through untouched. Confirmed this was real, not
  theoretical, with a live `TestClient` call before writing any fix:
  `POST /requests` with `rider_id="   "` and `contact="    "` returned
  `201` and stored both fields exactly as typed -- the identical
  "Matched! Your ride partner, :" / blank Contact line failure task 26
  was supposed to close, just one whitespace character away from it.
  `AbuseReportCreate.reason` (task 16) had the exact same
  `Field(min_length=1)` shape and the exact same gap -- a report whose
  `reason` is `"   "` is "stored," but exactly as uninformative as the
  empty string that field already rejects.
- Fix: `app/schemas.py`'s new `NonBlankStr` (`Annotated[str,
  Field(min_length=1), AfterValidator(_reject_blank)]`) rejects a value
  that's empty *after* `.strip()`, not just literally zero-length --
  replaces the bare `Field(min_length=1)` on `RideRequestCreate.rider_id`/
  `contact` and `AbuseReportCreate.reason`. Doesn't strip the stored
  value itself -- a real value with incidental surrounding whitespace
  (`" John "`) is left exactly as typed, only genuinely blank input is
  rejected. Left `RideRequest`/`AbuseReport` (the internal/stored shapes)
  untouched, same reasoning as task 26: `RideRequest` has to keep
  accepting an already-anonymized row's deliberately-blanked `contact`.
- Tests: `tests/test_schemas.py` adds a parametrized whitespace-variant
  case (space, multiple spaces, tab, newline-plus-space) for both
  `rider_id` and `contact`, plus one proving a real value's surrounding
  whitespace is preserved, not stripped. `tests/test_requests_api.py` adds
  the HTTP-level reproduction -- the exact `"   "`/`"    "` payload above
  now `422`s. `tests/test_reports.py` adds the same case for
  `AbuseReportCreate.reason`. Full suite: 147 tests, up from 136, all
  green.

### 26. Reject an empty rider_id/contact at intake instead of silently matching on them
- Not a numbered "Up next" item -- same pattern as the last several
  entries here: "Up next" only has tasks 13/19 on it and both are
  manual-only, so this morning run kept looking for a real bug instead of
  stopping, and found one right next to the lat/lng gap tasks 23/24 closed.
- `app/schemas.py`'s `RideRequestCreate.rider_id`/`contact` had no
  non-empty constraint -- confirmed with a direct call that
  `RideRequestCreate(rider_id="", ..., contact="")` validated cleanly.
  SCOPE.md is explicit about why `contact` exists at all ("collected at
  request time so a matched pair can reach each other"); an empty one
  sails through intake, gets stored, and can get matched exactly like a
  real one -- the counterpart's reveal (`app/web.py`'s `mine.html` /
  `app/static/live.js`) would then show "Matched! Your ride partner, :"
  and an empty Contact line, with literally no way to reach the person
  they just matched with. Silently defeats the one stated purpose of
  collecting the field, not a product/design call.
- Fix: `Field(min_length=1)` on both `rider_id` and `contact`, but only on
  `RideRequestCreate` (the intake boundary), not on `RideRequest` itself.
  Tried putting it on `RideRequest` first and broke two existing
  `tests/test_retention.py` tests -- `app/store.py`'s `_from_orm()`
  reconstructs a `RideRequest` straight from a stored row, including an
  already-anonymized one, and TASKS.md #17's `anonymize_stale()`
  deliberately overwrites `contact` with `""` on purpose as part of
  scrubbing a stale row. A constraint on `RideRequest` would have made
  that already-stored, intentionally-blanked state fail to load at all.
  `app/router.py`'s `create_request()` always builds `RideRequest` from
  an already-validated `RideRequestCreate`, so enforcing it only at that
  boundary doesn't weaken intake validation anywhere real client data
  flows through.
- Tests: `tests/test_schemas.py` covers `RideRequestCreate` directly
  (rejects an empty `rider_id` or `contact`) and proves `RideRequest`
  itself still accepts a blank `contact` (the anonymized-row case).
  `tests/test_requests_api.py` adds the HTTP-level reproduction --
  `POST /requests` with an empty `rider_id` or `contact` now `422`s.
  Checked the `POST /new` web-form path too: an empty `contact` there
  already 422s on its own, independent of this fix -- turns out
  Starlette's `Form(...)` already treats an empty-but-present form field
  as "missing" for a required field in the installed version, a
  pre-existing, unrelated quirk I didn't touch. Full suite: 136 tests, up
  from 131, all green.

### 25. Stop one bad request from permanently killing the live-matching pipeline
- Not a numbered "Up next" item -- "Up next" only has tasks 13 and 19 on it
  right now and both are manual-only, so this morning run went looking for
  a real bug the same way the last few runs did, and found one in
  `MatchingEngine.run_forever()`: the background task FastAPI starts once
  at app startup, with nothing that ever restarts it.
- `run_forever()`'s loop called `self.on_new_request(request)` inside a
  `try`/`finally` with no `except` -- `finally` ran `incoming.task_done()`
  either way, but any exception (a transient DB error from `store.save()`,
  or anything else unexpected) still propagated straight out of the `while
  True` loop and ended the task for good. Confirmed this was real, not
  theoretical: wrote a script that starts `run_forever()`, monkeypatches
  `on_new_request` to raise once, submits that request, then submits a
  second, completely normal one -- the task was dead
  (`task.done() == True`) after the first exception, and the second
  request just sat in `incoming` forever, `qsize() == 1`, never matched.
  `POST /requests` would still return `201` the whole time, since that
  response never depended on matching actually happening -- a caller
  would have no way to tell the entire live-matching pipeline had quietly
  died until they noticed nobody was ever matching again.
- Fix: wrap the loop body in `except Exception` that logs
  (`logger.exception(...)`) and moves on to the next queued request,
  instead of letting the exception escape the `while True` loop. The one
  request involved in a failure is dropped from that pass, not retried --
  retrying/backoff would be a bigger, separate design question than "the
  pipeline must not die," so I didn't build that here.
- Tests: new `tests/test_engine.py::test_run_forever_survives_on_new_request_raising`
  monkeypatches `on_new_request` to raise on the first call, then submits
  a real rider-1/rider-7 pair after it and asserts they still match on the
  same still-running worker (`not worker.done()`). Ran this test against
  the pre-fix code first to make sure it actually catches the regression
  -- without the fix it hangs forever on `await engine.incoming.join()`
  (the worker dies after the first item, so `task_done()` never gets
  called for the later ones), instead of just failing fast; with the fix,
  it passes normally. Full suite: 131 tests, up from 130, all green.

### 24. Reject physically-impossible coordinates in the dispatch module too
- Not a numbered "Up next" item -- "Up next" only has tasks 13 and 19 on it
  right now and both are explicitly manual-only, so this evening run went
  looking for a real bug the same way the last few runs did, and found one:
  the exact same gap task 23 just closed, but in the dispatch side-module's
  own `Location`, which wasn't touched by that fix since the two modules
  deliberately don't share schemas.
- `app/dispatch/schemas.py`'s `Location` had no range check on `lat`/`lng`
  either. Confirmed this was real with a live `TestClient`: `POST /match`
  with `rider_location.lat=999.0, lng=-500.0` returned `200` with a
  "nearest" driver and a `distance_miles` of several thousand -- a
  physically meaningless number computed from an impossible point, not
  even the kind of number a real location could ever produce, returned as
  if it were a normal match. `app/dispatch/matching.py`'s
  `haversine_miles` doesn't raise on this (checked the actual trig math:
  the haversine `h` term stays mathematically bounded in `[0, 1]`
  regardless of how far outside real-world range the input is, so there's
  no `math.asin` domain error either -- this is a silent-garbage bug, not
  a crash).
- Fix: same as task 23, same reasoning -- `lat`/`lng` are now
  `Field(ge=-90, le=90)` / `Field(ge=-180, le=180)`. `POST /match` now
  422s on an out-of-range `rider_location` instead of returning a bogus
  match; a normal in-range request right after it still works the same as
  before.
- Tests: new `tests/test_dispatch_schemas.py` mirrors
  `tests/test_schemas.py`'s coverage of the main `Location` (rejects just
  past each of the four bounds, accepts the poles/antimeridian themselves).
  `tests/test_dispatch_api.py` gets the HTTP-level reproduction as a
  regression test -- the exact `lat=999`/`lng=-500` case now `422`s. Full
  suite: 130 tests, up from 122, all green.

### 23. Reject physically-impossible coordinates instead of silently matching on them
- Not a numbered "Up next" item -- found this while poking at the API with
  edge-case inputs this run, same pattern as tasks 20-22: a pure
  data-validation bug against behavior SCOPE.md/docs/MATCHING_ALGORITHM.md
  already assume (real geographic coordinates everywhere), not a product
  call, so I'm closing it instead of just noting it.
- `app/schemas.py`'s `Location` had no range check on `lat`/`lng` at all.
  Confirmed this was real, not theoretical, with a live `TestClient`:
  `POST /requests` with `origin.lat=999.0, origin.lng=-500.0` returned
  `201`, and the request showed up on `GET /requests` with a real-looking
  H3 `origin_area` -- `app/geo.py`'s `haversine_miles`/`bearing_degrees`
  don't raise on an impossible point, `math.sin`/`math.cos` just keep
  going, so a client typo (or a bad Nominatim parse slipping past task
  10's geocoding wrapper some other way) would silently feed garbage
  distance/bearing numbers into the matching engine instead of getting
  rejected at intake, with nothing anywhere surfacing that the point was
  nonsense.
- Fix: `lat`/`lng` are now `Field(ge=-90, le=90)` / `Field(ge=-180,
  le=180)` -- real-world bounds, inclusive of the poles/antimeridian
  themselves. `POST /requests` now 422s on an out-of-range point instead
  of accepting it; `app/web.py`'s form path already had a catch-all
  `except (ValidationError, ValueError, TypeError)` around `Location`
  construction, so an out-of-range value there just re-renders the form
  with an error, no new code needed. Re-ran the same `TestClient` script
  after the fix: `422` with a clear `lat`/`lng` message, and a normal
  Fairfax-area request right after it still gets `201` -- the fix doesn't
  touch valid input.
- Tests: `tests/test_schemas.py` covers `Location` directly (rejects
  lat/lng just past each of the four real-world bounds, accepts the
  bounds themselves -- the poles and the antimeridian are valid points,
  not off-by-one rejects). `tests/test_requests_api.py`'s new test is the
  HTTP-level acceptance check -- `POST /requests` with the exact
  `lat=999`/`lng=-500` reproduction above now `422`s. Full suite (122
  tests, up from 114) still green.

### 22. Fix a 500 on browsing/posting an early-morning or late-night recurring request
- Not a numbered "Up next" item -- found it while reading `app/privacy.py`
  this run, same pattern as tasks 20/21: a pure bug against already-decided
  behavior (the fuzzing SCOPE.md already requires for every pre-match view
  has to actually not crash), not a product/design call, so I closed it
  instead of just noting it.
- `fuzz_schedule()`'s `_shift_time()` helper widens a `RecurringSchedule`'s
  bare `time`-of-day fields by `FUZZ_PADDING` (15min) on each end by
  combining the time with a throwaway date, shifting it, then dropping the
  date again -- and its own comment already said this "doesn't handle
  wrapping across midnight," reasoning that was "fine for this demo's
  daytime commute windows." That reasoning was wrong, not just imprecise:
  for a recurring window starting within 15 minutes of midnight (e.g.
  `earliest_departure_time=00:05`), subtracting 15 minutes and dropping the
  date wrapped the time back around to `23:50` the *previous* day -- which
  then reads as later than a same-day `latest_departure_time` and trips
  `RecurringSchedule`'s own "latest must not be before earliest" validator.
  Same thing in reverse for a window ending within 15 minutes of midnight.
  Confirmed this wasn't theoretical: posted a recurring request with
  `earliest_departure_time=00:05` through a real `TestClient` against a
  running app before the fix and watched `POST /requests` itself 500 (the
  response is built with `to_public()`, which calls `fuzz_schedule()`) --
  so this wasn't just `GET /requests`/`GET /requests/{id}`, posting an
  early-morning recurring request was broken outright. Re-ran the same
  script after the fix: `201` on the post, `200` on the follow-up `GET`,
  window correctly widened and clamped at `00:00:00`/`23:59:59.999999`
  instead of wrapping.
- Fix: `_shift_time()` now clamps the shifted time to the day's own
  `time.min`/`time.max` boundary instead of letting the dropped date wrap
  it. Since the original window already satisfies `latest >= earliest`
  (the schedule's own validator), and clamping can only move the widened
  earliest *up* toward the original and the widened latest *down* toward
  the original, the widened pair can never cross -- no crash is possible
  for any input, not just today's early-morning case, with no change to
  how `OneOffSchedule` fuzzing works (full datetimes, no wraparound to
  begin with).
- There was no direct test coverage of `app/privacy.py` at all before this
  -- `fuzz_schedule()`/`to_public()` were only ever exercised incidentally
  through API tests with ordinary daytime windows, never with an edge case
  that would catch this. New `tests/test_privacy.py` covers both normal
  widening (one-off and recurring) and this exact regression (both the
  early-morning and late-night wraparound cases), plus `to_public()`'s own
  no-contact/no-precise-location and computed-`expired`-status behavior
  directly rather than only through the HTTP layer.

### 21. Fix stored XSS in the live-match reveal (`live.js`)
- Not a numbered "Up next" item either -- found it while reading through
  the frontend this run, same as task 20 was found last time: a pure
  security/engineering fix against an already-decided requirement (the
  reveal has to actually be safe to render, not just correctly gated to
  the matched counterpart), not a product/design call, so I closed it
  instead of just noting it.
- `app/static/live.js`'s client-side reveal (the WebSocket path task 12
  built, as opposed to `mine.html`'s server-rendered/Jinja2-escaped path
  for a reload after the fact) built the matched counterpart's `rider_id`
  and `contact` straight into an HTML string and assigned it to
  `revealBox.innerHTML`. Both fields are free text another rider typed
  into `POST /requests` with zero sanitization -- SCOPE.md never asks
  `contact` to look like a phone number, it's just "contact info... same
  trust level as the group today" -- so anyone could post a request with
  `contact` (or `rider_id`) set to an `<img src=x onerror=...>` payload
  and have it execute in the browser of whoever they matched with, the
  instant the reveal rendered. Confirmed this was real, not theoretical,
  by temporarily swapping the pre-fix `live.js` back onto a running
  server and driving the actual flow with headless Chromium (Playwright):
  posted a rider with that payload as `contact`, had another rider match
  with them, and watched the `onerror` handler actually fire
  (`window.__xss_fired` flips to `true`, a real `<img>` element lands in
  the DOM) on the matched counterpart's `/mine/<id>` page. Re-ran the same
  script against the fixed version afterward: the payload shows up as
  literal text in the `<li>`, no `<img>` element, handler never fires.
- Fix: build the reveal with `document.createElement`/`textContent`
  (`addRevealItem()`) and `replaceChildren()` instead of a concatenated
  HTML string -- `textContent` never interprets its argument as markup,
  so this closes the hole for any string field here, not just today's PoC
  payload, with no allowlist/escaping logic to keep in sync by hand.
- No automated test added for this one: there's no JS test harness in
  this repo at all (`static/*.js` has always been manual-smoke-test-only,
  per TASKS.md #12's own note), and the real coverage here is the
  before/after Playwright run described above, not something `pytest`
  exercises. Worth a real JS test harness if `static/` grows much more --
  noting that as a gap, not fixing it in this same pass.

### 20. Make match explanations real, not a canned string (`ce600a1`)
- SCOPE.md's MVP item 6 says "for any match, the engine can state why --
  shared corridor, time overlap, capacity fit," but `MatchGroup.reason` was
  literally the same hardcoded sentence ("shared corridor, overlapping
  window, capacity fits") for every match `match_batch()`/
  `on_new_request()` ever produced -- it couldn't actually state why *this*
  pair matched versus any other, it just always said the same thing.
  Wasn't a numbered "Up next" item -- found it while reading through the
  matching engine this run, and it's a pure engineering fix against an
  already-decided requirement, not a product/design call, so I just closed
  it instead of only noting it for later.
- `app/matching/scoring.py`'s new `explain_match(a, b, window_a, window_b)`
  builds the explanation from the same numbers `compatibility_score()`
  already weighs -- origin/destination distance in miles, bearing
  difference in degrees, and the actual overlap in minutes between the two
  specific windows that produced the winning score -- so two different
  matches now read differently instead of printing the same sentence.
- Both `match_batch()` and `on_new_request()` (`app/matching/engine.py`)
  needed to start tracking *which* window pair actually produced the best
  score, not just the score itself (previously thrown away inside a `max()`
  generator expression) -- `explain_match()` needs the real overlapping
  windows to report a real overlap, not an arbitrary one.
- Tests (`tests/test_scoring.py`): `explain_match()` on the known-good
  rider-1/rider-7 pair actually names real distance/bearing/overlap/
  capacity language, and differs from the same call on a known-far pair
  (rider-1/rider-6) -- proving it's not still a canned string with extra
  words tacked on. `tests/test_engine.py`'s new test asserts the same thing
  at the `MatchGroup.reason` level `match_batch()` actually returns.

### 18. Deployment prep (the non-account parts of task 13) (`f8eb96d`)
- Task 13 itself is still off-limits to automated runs (hosting account,
  billing), but the app wasn't deploy-ready independent of that either --
  closing the gap the rule at the top of this file names: no health-check
  endpoint, no container image, and CORS/production config was whatever
  FastAPI's defaults happened to be.
- `GET /healthz` (`app/main.py`) actually runs `SELECT 1` against
  `request.app.state.session_factory` -- 200 when Postgres answers, 503
  when it doesn't -- instead of just confirming the process is up, which
  is what a hosting platform's health/readiness probe actually needs to
  know before routing traffic to a container. Reads `request.app`, not
  the module-level `app` global, so it's correct regardless of which app
  instance served the request (caught this the hard way via my own
  `test_cors.py`'s `importlib.reload` -- the old closure-over-the-global
  version silently started reading a *different* app's state once the
  module got reloaded).
- Replaced the old bare `GET /health` with this -- nothing else in the
  codebase or tests referenced that route, so there was no reason to keep
  both.
- `CORSMiddleware` (`app/main.py`) is now wired explicitly, controlled by
  a new `ALLOWED_ORIGINS` env var (`parse_allowed_origins()`,
  comma-separated). Unset -- the default, same as running locally -- adds
  no CORS middleware at all, same restrictive posture as before this
  task, just now a deliberate, documented choice instead of an unexamined
  default. FastAPI's own `debug` flag already defaults to `False` and
  nothing turns it on, so "debug off" needed documenting, not code.
- `backend/Dockerfile` builds the app and runs `alembic upgrade head`
  (no-op if already current) before starting `uvicorn --host 0.0.0.0`
  with no `--reload`, against whatever `DATABASE_URL`/`ALLOWED_ORIGINS`
  the container's given at run time -- never baked into the image.
  **Not yet verified by an actual `docker build`/`docker run`** -- this
  sandbox's Docker daemon can't be started here (no permission to run one
  inside this container, confirmed via `service docker start` and `docker
  info`), the same kind of real-environment limitation TASKS.md #10's
  geocoding and #12's browser checks already ran into. Worth a real build
  by hand on a machine with a working Docker daemon before trusting the
  image is actually correct, not just plausible-looking.
- New root README "Deploying" section documents all of the above
  (healthz, Dockerfile usage, `ALLOWED_ORIGINS`, debug) so task 13 really
  is just "sign up for hosting and point it at this" once it happens.
- Tests (`tests/test_health.py`, `tests/test_cors.py`): `/healthz` 200 on
  a real reachable test database and 503 when `session_factory` is
  swapped for one that raises; `parse_allowed_origins()` covered directly
  (empty/unset, one origin, several with stray whitespace); CORS
  middleware actually absent with `ALLOWED_ORIGINS` unset and actually
  restricting to the configured origin (via `importlib.reload`, since the
  middleware is wired once at import time from the env var) when it's
  set -- an unlisted `Origin` gets no
  `access-control-allow-origin` header back.

### 17. Data retention pass for matched/cancelled/expired requests (`e62270a`)
- SCOPE.md flags "real data protection for real location data" as a real
  requirement -- a matched, cancelled, or expired request's precise
  location and contact info used to just sit in Postgres forever with no
  cleanup. Decided on `RETENTION_DAYS = 30` (`app/retention.py`) -- SCOPE.md
  doesn't name a specific number, so this is my own reasonable
  data-minimization default, worth revisiting if a real policy is ever
  set.
- `app/retention.py`'s `terminal_at()` is the one place that decides *when*
  a request became retention-eligible: for `matched`/`cancelled` it's the
  new `status_changed_at` field (`app/schemas.py`, written by
  `MatchingEngine` on a match and by `POST /requests/{id}/cancel` on a
  cancel); for a still-`open`-but-expired one-off request (TASKS.md #14),
  it's that window's own `latest_departure` -- a `RecurringSchedule` never
  reaches this path since `is_expired()` already always returns `False`
  for one, matching docs/MATCHING_ALGORITHM.md's existing lifecycle
  write-up (now updated to mention this pass). `is_due_for_anonymization()`
  is just "has `RETENTION_DAYS` passed since then, and not already done."
- The actual mutation is `RequestStore.anonymize_stale()` (`app/store.py`):
  overwrites a due row's precise origin/destination with its own
  neighborhood-level H3 cell center (`app/geo.py`'s new `cell_center()` --
  same granularity every other user already sees pre-match, so this is
  genuinely "anonymized," not just hidden) and `contact` with an empty
  string, then stamps a new `anonymized_at` so a later run skips it
  instead of reprocessing. Only scans not-yet-anonymized rows, so repeated
  calls stay cheap.
- Deliberately didn't wire this to any in-app scheduler -- there's no
  cron/background-job infra in this app on purpose (TASKS.md #14's own
  reasoning), but unlike expiry, retention has to mutate stored rows, not
  just compute a display value at read time, so it needs a real external
  trigger. `scripts/anonymize_stale_requests.py` is that trigger -- run it
  by hand or from an external cron once deployed (TASKS.md #13/#18);
  documented in the root README's new "Data retention" section.
- Tests (`tests/test_retention.py`): `terminal_at()`/`is_due_for_
  anonymization()` covered directly (still-open/unexpired -> not due,
  matched/cancelled past the window -> due, matched not yet past the
  window -> not due, already-anonymized -> never due again). Then the
  real acceptance check against Postgres: a long-matched request's row
  actually gets its contact wiped and its precise point replaced (still
  the same coarse cell, just not the original lat/lng) after
  `anonymize_stale()` runs; a recently-matched or still-open request is
  left untouched; and running it twice is idempotent (second run
  anonymizes nothing new, keeps the original `anonymized_at`).

### 16. Minimal abuse/harassment reporting (`e439520`)
- SCOPE.md's "part that isn't just an engineering decision" names "some
  way to handle harassment/abuse reports" as needed before this goes live
  to real people -- nothing existed for this before this task.
- `POST /requests/{id}/report` (`app/router.py`) takes a `reason` (and an
  optional `reporter_request_id` -- the same no-login "proof of
  involvement" `viewer_request_id` already stands in for elsewhere,
  optional since someone just browsing the public list without ever
  posting a request of their own can still see something worth
  reporting). 404s if the reported request doesn't exist; 422s on an
  empty reason via Pydantic's `min_length=1` rather than silently storing
  a blank one.
- Own table (`abuse_reports`, `migrations/versions/0002_abuse_reports.py`),
  own store (`app/reports.py`'s `ReportStore`, mirroring `app/store.py`'s
  shape but write-only -- `add()` and nothing else), own ORM model
  (`AbuseReportORM` in `app/models.py`). Deliberately **no** FK to
  `ride_requests` and no GET route anywhere -- "stored durably, visible
  nowhere publicly" is this task's whole acceptance bar, not a
  moderation workflow or admin UI, which this explicitly doesn't build.
- Tests (`tests/test_reports.py`): `ReportStore.add()` survives a
  simulated restart the same way `tests/test_store_persistence.py` proves
  for `RequestStore` (a fresh session factory, not a shared Python
  object, has to be what returns the row); the HTTP route stores a real
  row keyed by the reported request's id, records
  `reporter_request_id` when given; an unknown request id 404s and
  writes nothing; an empty reason 422s and writes nothing; and a report's
  reason text never shows up in `GET /requests` or `GET /requests/{id}`'s
  response body. `tests/conftest.py` now truncates `abuse_reports`
  alongside `ride_requests` between tests.

### 15. Recurring-request lifecycle: cancel/withdraw + decide "expired" semantics (`ed3cae4`)
- The decision task 14 left open: I'm going with poster-initiated cancel
  as the *only* way a recurring request stops being matchable -- it never
  expires on its own. SCOPE.md never gives a recurring pattern an end
  date, so "today's occurrence already happened" was never going to mean
  "the whole standing request is dead" (tomorrow's occurrence hasn't).
  Per-occurrence expiry isn't something the current schema can even
  represent without a real redesign -- a recurring request is one
  `RideRequest`, not one row per weekday occurrence; `expand_schedule()`
  only materializes occurrences transiently, for scoring. Writing this
  down for real in docs/MATCHING_ALGORITHM.md's new "Request lifecycle"
  section instead of leaving it implicit, per this task's own acceptance
  wording.
- `POST /requests/{id}/cancel` (`app/router.py`) sets a new
  `RequestStatus.CANCELLED` (`app/schemas.py`) -- deliberately a distinct
  value from `EXPIRED`, since one is poster-initiated and stored, the
  other is time-based and computed, never stored. Works on both schedule
  shapes -- the endpoint only checks `status == OPEN`, doesn't care which
  schedule type it's cancelling -- so this also fills the plain gap
  SCOPE.md's "live status" item implies shouldn't exist: a one-off
  request had no way to be withdrawn before it matched either.
- Only an `open` request can be cancelled -- `matched`/`expired`/already-
  `cancelled` all 409 rather than silently no-op, so a caller can tell a
  real cancel happened from one that didn't. (A `matched` request already
  revealed contact info to its counterpart; there's no unmatch flow to
  build here.)
- The real reason this needed engine code, not just a status flip:
  `store.get()` hands the cancel endpoint a *fresh* `RideRequest`
  instance built from the DB row, not the same Python object sitting in
  `MatchingEngine._unmatched`'s pool -- flipping the fresh copy's status
  alone wouldn't stop the still-pooled one from winning a later match.
  `MatchingEngine.remove_from_pool(request_id)` (`app/matching/engine.py`)
  is what actually drops it from that pool, called right after the status
  flip.
- Tests: `tests/test_engine.py` covers `remove_from_pool()` directly
  (drops a pooled request by id, no-ops for an id never pooled) and this
  task's own acceptance wording -- a request removed from the pool can't
  win a later match that would otherwise have paired it (mirrors the
  known-good rider-1/rider-7 pair, same as task 14's expiry test).
  `tests/test_requests_api.py` covers the HTTP surface: a cancelled
  request reads back `cancelled` and drops out of `GET /requests`'
  open-only list, 404 on an unknown id, 409 on cancelling twice, and 409
  on cancelling an already-matched request.

### 14. Live status -- auto-expire past-window one-off requests (`64af644`)
- SCOPE.md's MVP item 4 ("live status: open / matched / expired... without
  the poster manually re-posting") named `expired` as a real state back in
  task 1, and `RequestStatus.EXPIRED` has existed in `app/schemas.py` since
  then, but nothing ever set it -- a one-off request whose window had
  fully passed just sat there showing `open` forever. `app/matching/
  scoring.py`'s new `is_expired(request, now=None)` is the one place that
  answers "has this window passed," and both read paths use it: `app/
  privacy.py`'s `to_public()` reports `expired` for a still-OPEN request
  whose window is behind `now` (computed at read time, not written back to
  the store -- no cron/background job needed, matching how `app/matching/
  engine.py` already only cares about the pool it holds in memory), and
  the engine (`match_batch()`/`on_new_request()`) skips an expired request
  or candidate rather than matching it, so an unread stale post can't
  quietly win a match slot a still-live request could use.
- Deliberately scoped to `OneOffSchedule` only. A `RecurringSchedule` is a
  standing weekly pattern with no end date SCOPE.md ever specifies -- "the
  Monday occurrence already happened" doesn't mean the whole recurring
  request should read as expired, since Tuesday's occurrence hasn't. Left
  `is_expired()` returning `False` for every recurring request rather than
  guessing at semantics (does a recurring request ever expire on its own,
  or only get cancelled by its poster -- and there's no cancel endpoint
  either). **Decision needed before this is closed for recurring
  requests**: what "expired" should mean for a standing pattern, and
  whether a cancel/pause action is the real fix here instead.
- Tests: `tests/test_scoring.py` covers `is_expired()` directly (past
  window true, upcoming window false, always false for recurring).
  `tests/test_engine.py` proves an expired request is excluded from
  `match_batch()` (never wins the slot the sample dataset's known-good
  rider-1/rider-7 pair would otherwise fill), and that `on_new_request()`
  neither matches nor pools an expired incoming request, nor matches
  against a pool candidate that expired while waiting.
  `tests/test_requests_api.py`'s new test posts a request with an
  already-past window and confirms both `POST /requests`' own response and
  a follow-up `GET /requests/{id}` and `GET /requests` all report
  `"status": "expired"`, with nothing in the store ever writing that value
  -- the actual HTTP-level acceptance check for SCOPE.md's "without the
  poster manually re-posting."

### 12. Minimal frontend — live matches + reveal (`ce2b9bf`)
- `GET /mine/{request_id}` (`app/web.py`) is the rider's own "waiting for a
  match" page -- lands there straight off `POST /new`'s redirect (changed
  from redirecting to `/browse`, since this page is what needs to know
  "my own request id"). `app/static/live.js` opens a WebSocket to the
  existing `/matches` route and, the moment a `MatchGroup` mentioning this
  page's own id arrives, calls `GET /requests/{counterpart_id}
  ?viewer_request_id={my_id}` (task 7's exact mechanism) and renders the
  reveal in place -- no reload. If the request is already matched when the
  page loads (e.g. a reload after the fact), the reveal renders
  server-side instead of waiting on a WebSocket event that already fired.
- Fixed a real gap this task's own acceptance criterion (two browser tabs,
  both see the same match) would have failed on: `WS /matches` used to
  read every connection off one shared `engine.matches` queue,
  competing-consumer style -- task 6's own docstring already flagged this
  as fine "for a single subscriber" but not built for more. Two
  simultaneous tabs need the *same* match event each, not one queue split
  between them, so `MatchingEngine.subscribe()`/`unsubscribe()`
  (`app/matching/engine.py`) hand out one independent queue per WebSocket
  connection, and `run_forever()` now feeds every subscriber, not just the
  original `self.matches` queue (kept as-is for `test_engine.py` and
  `simulate.py`'s existing single-subscriber usage).
- Tests: `tests/test_engine.py`'s new
  `test_run_forever_broadcasts_match_to_every_subscriber` proves two
  `subscribe()`'d queues both get a copy of the same match.
  `tests/test_live_matches.py` proves the same thing at the HTTP/WS level
  (two simultaneous `TestClient` WebSocket connections both receive one
  match), and that `/mine/{id}` renders "waiting" before a match and the
  correct counterpart's reveal (never your own contact) after one.
  `tests/test_web_frontend.py` updated for the new `/mine/<id>` redirect
  target (was `/browse`).
- Manually verified the actual acceptance criterion -- two browser tabs,
  live update, no reload -- with a headless-Chromium (Playwright) script
  against a live server, since this sandbox has no real browser to drive
  by hand and `/geocode`'s real network call is blocked here the same way
  TASKS.md #10 documents (the script stubs only that one endpoint, the
  rest of the flow -- posting, redirecting, the live WebSocket update, the
  reveal -- runs for real). That run surfaced and led to fixing a real bug
  in `app/static/app.js`: a failed `/geocode` call was treating a
  transient 500 the same as a confirmed 404 "not found," clearing a
  hidden lat/lng field the rider had already filled in correctly. Steps
  to reproduce this by hand are in the root README's new "Web frontend"
  section.

### 11. Minimal frontend — submit + browse (`2b5fac9`)
- `app/web.py` adds `GET`/`POST /new` (the submission form) and
  `GET /browse` (the open-requests list), served as plain Jinja2 templates
  (`app/templates/`) plus one vanilla-JS file (`app/static/app.js`) --
  `StaticFiles`/`Jinja2Templates` off the same FastAPI app, no separate
  frontend process, per this task's own wording.
- The form collects free-text place names, not raw coordinates --
  `app.js` calls task 10's `GET /geocode` on blur and fills hidden
  `origin_lat`/`origin_lng`/`destination_lat`/`destination_lng` inputs, so
  the actual `POST /new` body is the same lat/lng shape the JSON API
  already expects. A failed geocode, or any other validation problem,
  re-renders the form with an error and everything the rider already
  typed rather than clearing the form.
- `POST /new` builds a `RideRequestCreate` and calls `app/router.py`'s
  `create_request()` directly instead of reimplementing intake -- one more
  caller of the existing store/engine pipeline, not a second one with its
  own rules. `GET /browse` renders the same `to_public()` coarse view
  `GET /requests` already returns, so there's no new redaction logic here
  to get wrong.
- The form supports both schedule shapes (one-off window, recurring
  weekdays), not just one-off -- SCOPE.md calls recurring "first-class,"
  and the whole point of a structured form over the WhatsApp group is not
  making people repost the same request daily.
- Tests (`tests/test_web_frontend.py`) hit the page routes themselves
  through `TestClient`, per this task's own acceptance wording: `GET /new`
  renders a form, `POST /new` (both one-off and recurring) redirects to
  `/browse` and the posted rider shows up there, and neither the precise
  coordinates nor the contact info leak onto that page. Also manually
  verified against a live `uvicorn` instance with `curl` (no browser in
  this sandbox) -- posted through `/new`, confirmed the rider shows up on
  `/browse` and the contact string doesn't.
- Added `jinja2` and `python-multipart` to `requirements.txt` --
  `Jinja2Templates` and FastAPI's `Form()` parsing both need them and
  neither came in transitively already.

### 10. Geocoding — informal place names to coordinates (`cce8747`)
- `app/geocoding.py`'s `geocode_place()` wraps Nominatim's `/search`
  endpoint: a `viewbox` covering every town SCOPE.md names (Fairfax,
  Ashburn, Herndon, Chantilly, Reston, Aldie, Manassas, Sterling, South
  Riding, Vienna, Falls Church, Centerville) plus `bounded=1` so a place
  name never silently resolves to a same-named place outside Northern
  Virginia, a real identifying `User-Agent` (not a browser spoof), and a
  module-level `_wait_for_rate_limit()` that sleeps as needed to respect
  Nominatim's 1-request/second usage policy across calls, not just
  document it. An empty/blank place name is rejected before any HTTP call
  is made; no match, or any HTTP error, raises rather than returning a
  guessed location.
- `GET /geocode?q=<place name>` (`app/router.py`) is the seam this task's
  own wording asks for -- "before it reaches the existing `POST
  /requests` shape, the request schema itself doesn't change" --
  `RideRequestCreate` is untouched; this is what a client (task 11's
  frontend) calls first to turn free text into the `Location` that
  endpoint already expects. 404s with the place name in the error detail
  on no match.
- This sandbox's network policy denies `nominatim.openstreetmap.org`
  outright (confirmed by the 2026-08-28 morning run, via the agent-proxy
  status endpoint -- a policy `403`, not a timeout or a Nominatim-side
  rate limit), and almost any external API would hit the same wall, so
  switching providers wouldn't have helped either -- decided to keep
  Nominatim and have automated runs build/test this with `httpx.get`
  mocked only. `tests/test_geocoding.py` covers the viewbox/User-Agent
  request shape, the empty-input short-circuit, the not-found path, HTTP
  errors propagating instead of a silent wrong match, the rate limiter's
  sleep math, and the `/geocode` route's 200/404 paths through a real
  `TestClient`. None of this calls the real API, and none of it is
  credited as verifying the live half of this task's acceptance
  criterion.
- **Not yet manually verified.** This run (like the ones before it) is
  the sandboxed automated environment that can't reach
  `nominatim.openstreetmap.org` at all -- so per the decision above, I'm
  marking the mocked half of this task done and leaving the live check
  (`GET /geocode?q=...` against a real running server, from a session
  with normal network access) as a real to-do for me, by hand, before I'd
  call this fully trustworthy. Steps are in the README's new "Geocoding"
  section.

### 1. Data models + sample dataset (`46966dd`)
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

### 2. Spatial bucketing (`9c0670d`)
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

### 3. Compatibility scoring (`1158014`)
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

### 4. Greedy matching engine (`6e36739`)
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

### 5. Incremental matching + in-process pub/sub (`f236525`)
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

### 6. Structured intake + privacy-safe read API (`b22259a`)
- `app/router.py` adds `POST /requests` (structured `RideRequestCreate`
  body, no free text -- task 1's form fields directly) and `GET /requests`
  (coarse area + fuzzed window only). `WS /matches` streams each
  `MatchGroup` as the engine finds it.
- `POST /requests` doesn't match inline -- it stores the request in a new
  `app/store.py` `RequestStore` (all requests, any status; separate from
  `MatchingEngine._unmatched`, which drops a request the moment it's no
  longer relevant to bucketing) and `await`s `engine.submit()`, letting
  task 5's `run_forever()` pipeline do the actual matching in the
  background -- now actually started, as a FastAPI lifespan task in
  `app/main.py`, which is what that function's own docstring said task 6
  should do.
- `engine`/`store` live on `app.state`, set up fresh in the lifespan, not
  as module-level singletons -- so every `with TestClient(app) as
  client:` block in a test gets its own empty pool instead of leaking
  matched requests into the next test.
- `app/privacy.py`'s `to_public()` is the one place a full `RideRequest`
  becomes the coarse/fuzzed `RideRequestPublic` shape: `Location.coarse_cell()`
  (task 1) for both origin and destination instead of lat/lng, and
  `fuzz_schedule()` widens the departure window by 15 minutes on each
  side (`FUZZ_PADDING`) so the fuzzed window never reveals the real one
  even when the posted window is already narrow. `contact` never appears
  in this path at all.
- `WS /matches` reads directly off `engine.matches`, so with more than one
  connection open, matches split competing-consumer style instead of
  broadcasting to every subscriber -- fine for a single subscriber (task
  8's simulator/live view); real fan-out would need a per-connection
  queue, not worth building before something needs it.
- Tests (`tests/test_requests_api.py`) cover: the privacy-shaping
  acceptance criterion itself (a precise-location, real-contact request
  posted, then asserted absent from both the `POST` response and `GET
  /requests`, by key and by substring); the fuzzed window actually being
  wider than the one posted; and a `TestClient` websocket test proving a
  same-corridor pair (mirroring the sample dataset's rider-1/rider-7
  fixture) shows up as a match event on `/matches` after two `POST`s, not
  just in the return value of some function. Manual curl/websocket smoke
  test documented in the root README.

### 7. Post-match reveal (`bee4d17`)
- `RideRequest` gets a new `matched_with: Optional[UUID]` field, set by
  `MatchingEngine` (both `match_batch()` and `on_new_request()`) right
  alongside the existing `status = MATCHED` flip -- so a matched pair's
  linkage lives on the request objects themselves, the same objects
  `RequestStore` already holds, with no new plumbing needed to get it from
  engine to store.
- `GET /requests/{request_id}` (`app/router.py`) returns the coarse/fuzzed
  `to_public()` view (task 6) to anyone, *except* when the caller passes
  `viewer_request_id` equal to that request's `matched_with`, in which
  case it returns the full `RideRequest` (precise `Location` + `contact`).
- There's no login/session system (SCOPE.md: no SMS/OTP for the MVP), so
  `viewer_request_id` -- the caller's own request id, handed back by
  `POST /requests` and never shown to anyone else -- is standing in as
  the one proof of "I'm the matched counterpart." Same open, no-membership
  trust model SCOPE.md already accepts for contact exchange itself,
  applied one step earlier to who gets to ask; noting this here in case
  a real auth story ever needs to replace it.
- Tests (`tests/test_requests_api.py`): the matched counterpart's request
  gets the full view (real `contact`, real `origin`), a random/absent/
  even the *same* request's own id as `viewer_request_id` all still get
  the redacted view, an unmatched request's own `GET` is redacted too, and
  an unknown id 404s.

### 8. Simulator + minimal live view (`033f6cf`)
- `backend/simulate.py` replays `app/sample_data.py`'s `SAMPLE_REQUESTS`
  against a *running* server (`POST /requests`, staggered across a
  compressed `--seconds` window, default 15s) while a second `asyncio`
  task subscribes to `WS /matches` the whole time and prints each match as
  it arrives -- interleaved with the posts, not batched at the end, which
  is the acceptance criterion itself and the actual point: proving
  task 5's incremental pipeline is real-time, not a batch job wearing a
  websocket.
- The two tasks are coordinated with an `asyncio.Event` the subscriber
  sets once its websocket is actually connected, so the publisher never
  starts posting before there's a subscriber to miss an early match (the
  matches queue wouldn't lose it either way -- `WS /matches` reads off
  `engine.matches`, a queue, so a match posted before any subscriber
  connects just waits there -- but connecting first makes the run's timing
  honest instead of accidental). Racing that same event against the
  subscriber task's own completion (via `asyncio.wait(...,
  return_when=FIRST_COMPLETED)`) is what turns "server isn't running" into
  an immediate, readable error instead of hanging forever waiting for a
  websocket that's never going to connect -- caught this the hard way
  running it against a killed server before writing the fix.
- Manually verified against a live `uvicorn` instance (not something
  `pytest` covers, since the acceptance criterion is about a running
  process's interleaved output, not a return value): `rider-7`'s POST at
  ~4.1s produces a `MATCH rider-7 <-> rider-1` line at that same ~4.1s
  mark, three full posts (rider-8/9/10) before the run even finishes --
  see the root README's new "Simulator" section for the command.
- Added `websockets` to `requirements.txt` as a direct dependency, since
  `simulate.py` imports it directly rather than relying on it coming along
  transitively through `uvicorn[standard]`.

### 9. Persistence: PostgreSQL-backed request store (`7f26a0d`)
- `app/store.py`'s `RequestStore` is now Postgres-backed: `app/models.py`
  has the SQLAlchemy `RideRequestORM` table, `app/db.py`'s
  `make_session_factory()` builds a session factory from `DATABASE_URL`
  (always read from the environment, never hardcoded), and `migrations/`
  is a real Alembic setup (`0001_initial.py`) -- schema changes go through
  a migration, not `Base.metadata.create_all()`.
- The schedule union (`OneOffSchedule | RecurringSchedule`) doesn't map to
  a single SQL column, so the table stores `schedule_type` +
  a JSONB `schedule` blob, and `app/store.py`'s `_to_orm`/`_from_orm` are
  the one place that conversion happens -- mirrors how `app/privacy.py`'s
  `to_public()` is the one place the public-view conversion happens.
- `MatchingEngine` takes an optional `store` (default `None`, so every
  existing `MatchingEngine()` call in `test_engine.py` is unaffected) and
  calls `store.save(request)` right where it already flips `status`/
  `matched_with` on a match, in both `match_batch()` and
  `on_new_request()` -- so a match survives a restart the same way the
  original open request does, without engine.py needing to know anything
  about SQL. `app/main.py`'s lifespan wires `MatchingEngine(store=...)`.
- Deliberately did **not** rebuild `MatchingEngine._unmatched` from the
  store on startup -- that pool stays in-memory/ephemeral by design (it's
  a bucketing working set, not the source of truth) and TASKS.md's own
  acceptance wording only asks for `GET /requests[/{id}]` to survive a
  restart, not for in-flight matching to resume mid-pool. Worth revisiting
  if a real restart losing not-yet-matched requests' matchability turns
  out to matter in practice.
- Tests (`tests/test_store_persistence.py`): a request posted through one
  `RequestStore`/session factory is still there through a second,
  independent one pointed at the same database (the literal "simulate a
  restart" acceptance criterion), same for `list_open()`, and a `save()`
  status flip persists across that same restart simulation too.
  `tests/conftest.py` runs the real `alembic upgrade head` against a local
  `fairfax_ridesharing_test` database once per test session (not
  `create_all()`, so the migration itself is what's under test) and
  truncates `ride_requests` between tests. `test_requests_api.py` passes
  completely unchanged -- confirmed with a diff-free `git status` on that
  file -- since the store's public interface (`add`/`get`/`list_open`)
  didn't change shape, only its backing.
- Manually verified restart-survival at the actual HTTP level too, not
  just via the store directly: posted a request to a live `uvicorn`
  process, killed it, started a fresh process against the same
  `DATABASE_URL`, and `GET /requests/{id}` still returned it.
- Added `sqlalchemy`, `alembic`, and `psycopg2-binary` to
  `requirements.txt`, and documented local Postgres setup (dev + the
  separate test database) in the root README.

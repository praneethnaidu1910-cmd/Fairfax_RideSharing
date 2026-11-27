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

### 59. Cap rider_id/contact/report-reason length so one POST can't bloat every future GET /requests response
- Not a numbered "Up next" item -- "Up next" only has tasks 13/19 on it and
  both are manual-only, so this morning run went looking for a real bug the
  same way the last several runs did, and found the missing ceiling on the
  exact fields task 58 (and 26/27 before it) already put a floor on --
  `app/schemas.py`'s `NonBlankStr`, shared by `RideRequestCreate.rider_id`,
  `.contact`, and `AbuseReportCreate.reason`.
- `Field(min_length=1)` plus `_reject_blank`/`_reject_nul` already stop
  these fields from being empty, whitespace-only, invisible-characters-
  only, or carrying a NUL byte -- but nothing anywhere put a *ceiling* on
  how long one can be. `app/models.py`'s backing columns are a plain
  SQLAlchemy `String` with no length, which Postgres stores as an
  unbounded `VARCHAR` without complaint, so there was no DB-level limit to
  lean on either -- unlike `seats_needed`'s own `MAX_SEATS_NEEDED` fix,
  which closes a real Postgres INTEGER column limit, there was nothing
  here to hit a wall on at all. Confirmed this was real, not theoretical,
  with a live `TestClient` call before writing any fix: `POST /requests`
  with a 50,000-character `rider_id` and `contact` (one ordinary-shaped,
  unauthenticated POST -- SCOPE.md: open-join, no SMS/OTP) validated
  cleanly and came back a real `201`, and the very next `GET /requests` --
  the open list every anonymous caller/browser polls -- came back as a
  5MB+ response, just from that one row. That's not a one-time cost: it's
  paid by every caller of that public list for as long as the request
  stays open, which is indefinite for a recurring request
  (docs/MATCHING_ALGORITHM.md's "Request lifecycle" section: a
  `RecurringSchedule` never expires on its own). The same gap reached
  `AbuseReportCreate.reason` through `POST /requests/{id}/report`, since it
  shares the same `NonBlankStr` type. Same "one reachable POST degrades
  everyone else" shape as task 56's duplicate-weekday fix and task 50/55's
  datetime-range fixes already in this log, just on string length instead
  of list length or a datetime bound.
- Fix: a new `MAX_TEXT_FIELD_LENGTH = 500` and `max_length=
  MAX_TEXT_FIELD_LENGTH` added to `NonBlankStr`'s existing `Field(...)`.
  SCOPE.md never states a number for this, the same situation
  `app/retention.py`'s `RETENTION_DAYS` is already in, so 500 is my own
  reasonable default -- comfortable room for a real name, a phone number
  or WhatsApp handle, or a genuinely detailed abuse-report paragraph,
  several times over -- not a hard system limit the way `MAX_SEATS_NEEDED`
  is. Worth revisiting if a real policy is ever set. Deliberately left
  `RideRequest.rider_id`/`.contact` (the stored/internal shape) and
  `AbuseReport.reason` untouched -- same reasoning task 58's own fix
  already gives for why those aren't `NonBlankStr`-typed: `RideRequest`
  also has to represent an already-stored row, and by the time either
  shape is ever constructed, intake (`RideRequestCreate`/
  `AbuseReportCreate`) has already enforced the ceiling.
- Tests: `tests/test_schemas.py` adds
  `test_ride_request_create_rejects_a_rider_id_or_contact_past_the_length_ceiling`
  and
  `test_ride_request_create_keeps_a_rider_id_or_contact_exactly_at_the_length_ceiling`
  (the boundary itself, both fields) directly against `RideRequestCreate`.
  `tests/test_requests_api.py` adds
  `test_create_request_rejects_a_rider_id_or_contact_past_the_length_ceiling`,
  the real `POST /requests` reproduction above (50,000-character fields).
  `tests/test_reports.py` adds
  `test_post_report_with_a_reason_past_the_length_ceiling_is_rejected`, the
  same shape through `POST /requests/{id}/report`. Ran the three HTTP-level
  reproductions against the pre-fix code first (temporarily stashing just
  `app/schemas.py`) to confirm they actually fail there -- a real `201`
  instead of `422` on both, not just that they pass now; the two
  `test_schemas.py` tests fail to even import pre-fix, since
  `MAX_TEXT_FIELD_LENGTH` doesn't exist yet. Full suite: 231 tests, up from
  225, all green.

### 58. Reject a rider_id/contact/report-reason made up of only invisible Unicode characters, not just whitespace
- Not a numbered "Up next" item -- "Up next" only has tasks 13/19 on it and
  both are manual-only, so this evening run went looking for a real bug the
  same way the last several runs did, and found a narrower sibling of tasks
  26/27's own "whitespace-only" fix in `app/schemas.py`'s `_reject_blank()` --
  same purpose, same shape of gap, just a different kind of input that looks
  blank to a person without being blank to `str.strip()`.
- `_reject_blank()` already rejects the empty string and a whitespace-only
  one (" ", "\t\n ") for `rider_id`/`contact`/an abuse report's `reason` --
  every field whose whole point is reaching or informing a real person. But
  `str.strip()` only recognizes actual whitespace; it leaves a Unicode
  "format" character (category Cf) completely alone, and that category is
  exactly the zero-width/invisible characters a real client can type or
  paste without anyone noticing: zero-width space (U+200B), zero-width
  joiner/non-joiner, the BOM/zero-width-no-break-space (U+FEFF), the
  left-to-right/right-to-left marks. None of those render as anything, so a
  `rider_id`/`contact` made up of only them is exactly as blank to the
  matched counterpart's reveal ("Matched! Your ride partner, :" / a blank
  Contact line -- the precise gap task 26 first closed) as "   " already
  is, just invisible instead of using spaces. Confirmed this was real, not
  theoretical, with a live `TestClient` call before writing any fix: `POST
  /requests` with `rider_id="​​​"` and
  `contact="﻿‌"` validated cleanly through `_reject_blank()`
  (`value.strip()` doesn't touch either character) and returned a real
  `201`, not the `422` this function's whole job is to produce for exactly
  this shape of input.
- Fix: `_reject_blank()` now rejects a value where *every* character is
  either whitespace or Unicode category Cf, instead of checking
  `not value.strip()` alone -- this subsumes the existing empty/
  whitespace-only cases (an empty string trivially satisfies "every
  character is X" with zero characters to check) while also catching a
  value that's only invisible format characters, or a mix of both
  (" ​ "). Deliberately narrow: doesn't touch a Unicode letter that
  happens to render with no visible glyph in some fonts (e.g. Hangul filler,
  category Lo, a real letter rather than a format-control character) --
  category Cf is specifically "characters designed to be invisible," the
  same class of trick as the zero-width/BOM tokens actually confirmed above,
  not a broader judgment call about what counts as a "real" character. Still
  doesn't strip or normalize the value itself -- a real value that merely
  *contains* an incidental invisible character alongside real content (e.g.
  a stray zero-width space pasted into the middle of a name) is left
  exactly as typed, same as this function's existing stance on incidental
  whitespace.
- Tests: `tests/test_schemas.py` adds
  `test_ride_request_create_rejects_a_rider_id_or_contact_made_only_of_invisible_characters`
  (four invisible-only payloads, both fields) and
  `test_ride_request_create_keeps_a_real_value_with_an_incidental_invisible_character`
  (a real value with one incidental invisible character isn't over-rejected).
  `tests/test_requests_api.py` adds
  `test_create_request_rejects_a_rider_id_or_contact_made_only_of_invisible_characters`,
  the real `POST /requests` reproduction above. `tests/test_reports.py` adds
  `test_post_report_with_a_reason_made_only_of_invisible_characters_is_rejected`,
  the same shape through `POST /requests/{id}/report`. Ran all four against
  the pre-fix code first (temporarily stashing just `app/schemas.py`) to
  confirm they actually fail there -- a real `201` instead of `422` on all
  of them, not just that they pass now. Full suite: 225 tests, up from 214,
  all green.

### 57. Stop a /matches connection that disconnects after registering from leaking its subscriber slot forever
- Not a numbered "Up next" item -- "Up next" only has tasks 13/19 on it and
  both are manual-only, so this morning run went looking for a real bug the
  same way the last several runs did, and found the sibling of a leak I'd
  already closed once in this exact route (`stream_matches()`,
  `app/router.py`) -- that fix covered a connection that never registers at
  all; this one's about every connection that does register and then
  genuinely goes away.
- Once a connection registers, the only thing left running was
  `while True: match = await queue.get()` -- it never calls
  `websocket.receive()` again for the rest of the connection's life, and
  `app/static/live.js` never sends a second message anyway. That's exactly
  how an ASGI server like uvicorn finds out a client disconnected: it
  delivers the `websocket.disconnect` message the *next* time the app
  calls `receive()` -- it doesn't cancel the app's own task on its own just
  because the underlying TCP connection dropped. So a connection that
  closes the tab, loses network, or (the ordinary case once it's already
  matched) just navigates away from `/mine/<id>` never calls `receive()`
  again here, that disconnect message never gets read, and this loop sits
  in `queue.get()` forever -- still in `engine._subscribers`, still handed
  a `put()` for every future match anyone else makes, for as long as the
  process runs, exactly the kind of thing SCOPE.md's real ~1,000-person
  deployment would hit constantly (most riders either never match before
  closing the tab, or close it right after matching -- either way nothing
  ever arrives afterward to clean them up the old way). Confirmed this was
  real, not theoretical, with a live script against a *real* uvicorn
  server, not just this suite's own TestClient -- TestClient cancels the
  server-side task directly when its own `with` block exits, which isn't
  how a real dropped connection behaves and would have hidden this bug
  completely: opened a raw socket, completed the WebSocket handshake and
  sent a real registration message by hand, then aborted the TCP
  connection outright (no close handshake, same as a lost network or a
  killed browser tab) -- `engine._subscribers` still held that
  connection's queue, unchanged, for as long as the server kept running
  afterward with no later match for its id ever arriving.
- Fix: a second task, `_watch_for_disconnect()`, now runs alongside the
  match-forwarding loop (renamed `_forward_matches()`) for the rest of the
  connection's life, doing nothing but calling `receive()` in a loop so a
  real disconnect is actually noticed the moment it happens instead of
  only if a match happens to arrive afterward. `asyncio.wait(...,
  return_when=FIRST_COMPLETED)` races the two; whichever finishes first
  (a real disconnect, or -- on correctly-behaving code -- nothing, since
  match-forwarding runs forever) causes the other to be cancelled, and the
  same `finally: engine.unsubscribe(queue)` as before always runs.
- Tests: `tests/test_live_matches.py` adds
  `test_a_connection_that_disconnects_after_registering_is_unsubscribed_even_without_a_later_match`
  -- reproduces the same shape without a second real socket by sending the
  raw ASGI `websocket.disconnect` message this connection's own `receive()`
  would get from a real dropped connection, *while still inside* the
  `with` block (not via it exiting, which would cancel the server task
  directly and mask this exact bug the same way it would have hidden the
  live-uvicorn repro above), then polls `engine._subscribers` briefly
  rather than a fixed sleep, since crossing from synchronous test code
  into the server's own background async task is inherently a race
  against its next scheduling tick. Ran it against the pre-fix code first
  (temporarily stashing just `app/router.py`) to confirm it actually fails
  there -- `engine._subscribers` still held the leaked queue after the
  full 2-second poll window, not just that it passes now. Full suite: 214
  tests, up from 213, all green.

### 56. Reject a repeated weekday on a recurring schedule instead of letting it multiply matching cost per duplicate
- Not a numbered "Up next" item -- "Up next" only has tasks 13/19 on it and
  both are manual-only, so this evening run went looking for a real bug the
  same way the last several runs did, and found one in
  `app/schemas.py`'s `RecurringSchedule` -- a missing validation gap with a
  real resource-exhaustion shape, not a crash/race/leak the way most of
  the last several entries here were.
- `RecurringSchedule.weekdays` means "which days of the week" -- a set of
  at most 7 distinct values, Monday=0 through Sunday=6. The existing
  validator already rejected an out-of-range value (`weekdays=[7]`) and an
  empty list, but nothing stopped a value from *repeating* -- every
  individual entry in `weekdays=[0, 0, 0, ...]` is still in range, so that
  sailed through cleanly. That's not just a wasted payload:
  `app/matching/scoring.py`'s `expand_schedule()` materializes one
  `OneOffSchedule` instance per entry in this list, duplicates included,
  and both `match_batch()` and `on_new_request()` then score *every one of
  those windows* against every window on the other side of a candidate
  pair -- so the cost of scoring this one request against anything else
  scales linearly with how many duplicates it was posted with, not with
  how many distinct days it actually represents. Confirmed this was real,
  not theoretical, with a live script before writing any fix: pooling one
  request with `weekdays=[0]*20000` (a single, ordinary-looking
  `POST /requests`, no auth required -- SCOPE.md: open-join, no SMS/OTP)
  and then submitting one unrelated, otherwise-compatible request next to
  it took `on_new_request()` from sub-millisecond to ~180ms for that one
  call alone. And because a `RecurringSchedule` never expires
  (`scoring.is_expired()` always returns `False` for one) and
  `can_ever_be_matched()` only looks at seat count, a small enough
  `seats_needed` keeps a request shaped like this sitting in the live
  matching pool, repeatedly re-scored against every future candidate that
  happens to bucket near it, for as long as the process runs -- a real,
  single-POST way to make every subsequent nearby match slower, not a
  contrived one.
- Fix: `RecurringSchedule._check_weekdays_and_window()` now also rejects
  `len(self.weekdays) != len(set(self.weekdays))` -- a repeated weekday is
  meaningless on its own terms (two "Mondays" produce two identical
  expanded windows, not two different ones), so rejecting it isn't
  inventing a new product rule, it's enforcing what `weekdays` already
  claims to represent. This also naturally caps a valid `weekdays` at 7
  entries, since there are only 7 distinct values (0-6) to begin with --
  closing the resource-exhaustion shape at the source instead of picking
  an arbitrary length limit.
- Tests: `tests/test_schemas.py` adds
  `test_recurring_schedule_rejects_duplicate_weekdays`, directly against
  `RecurringSchedule`. `tests/test_requests_api.py` adds
  `test_create_request_rejects_a_recurring_schedule_with_duplicate_weekdays`,
  the real `POST /requests` reproduction (a small, 3-element duplicate
  list, not the 20000-element one used to measure the actual cost above).
  Ran both against the pre-fix code first (temporarily stashing just
  `app/schemas.py`) to confirm they actually fail there -- a real `201`
  instead of `422`, not just that they pass now. Full suite: 213 tests, up
  from 211, all green.

### 55. Stop a NaN/Infinity coordinate from crashing the 422 response that was supposed to reject it
- Not a numbered "Up next" item -- "Up next" only has tasks 13/19 on it and
  both are manual-only, so this evening run went looking for a real bug the
  same way the last several runs did, and found one in how FastAPI's own
  default validation-error handler reports the exact bug tasks 23/24
  already fixed once -- not in app/schemas.py's `Location` itself, which
  is doing exactly what it's supposed to.
- `Location.lat`/`lng` (here and in app/dispatch/schemas.py's own copy)
  already range-check with `Field(ge=.., le=..)` -- tasks 23/24's own fix
  for a client typo like `lat=999` silently feeding nonsense into the
  distance/bearing math instead of 422ing. But Python's own `json.loads()`
  -- what Starlette's `Request.json()` uses to parse every request body --
  accepts the non-standard `NaN`/`Infinity`/`-Infinity` tokens as real
  float literals, unlike strict JSON. That value reaches pydantic as an
  actual `float('nan')`, correctly fails the `ge`/`le` check (any
  comparison against NaN is False, so it's never mistaken for a valid
  number -- same mechanism that already rejects `lat=999`), and pydantic's
  own error object faithfully echoes the bad value back as
  `error['input']`, exactly like it does for any other rejected value.
  That's where it stopped being fine: FastAPI's default handler builds the
  422 body with `jsonable_encoder(exc.errors())`, which leaves a
  NaN/Infinity float completely untouched (confirmed directly --
  `jsonable_encoder(float('nan'))` hands back `nan`, not a string), and
  Starlette's `JSONResponse` renders that body with `json.dumps(...,
  allow_nan=False)` -- deliberately strict, since a literal NaN/Infinity
  isn't valid JSON for any other caller to read back. Confirmed real, not
  theoretical, with a live TestClient call before writing any fix: `POST
  /requests` with `{"origin": {"lat": NaN, "lng": -77.3}, ...}` (valid
  Python-flavored JSON, parses cleanly, and lat correctly fails its own
  bounds check) didn't 422 at all -- it 500'd, and running the same thing
  against a real raw socket reset the connection outright, since the crash
  happened *while building* the error response itself. `POST /match`
  (app/dispatch/router.py) hits the identical crash through its own
  `Location`, since it has the same `Field(ge=.., le=..)` shape with
  nothing dispatch-specific about the bug.
- Fix: a new `app.main._json_safe()` and a `RequestValidationError`
  exception handler registered on the app that uses it -- recursively
  replaces any NaN/+-Infinity float anywhere in the error payload (not
  just at the top level: a nested model's error can bury the bad float
  several levels into `error['input']`/`error['ctx']`) with its own
  `str()` (`"nan"`/`"inf"`/`"-inf"`), then builds the exact same 422
  `{"detail": [...]}` shape FastAPI's own default handler already builds
  for every other validation error -- ordinary out-of-range values like
  `lat=999` are untouched by this (`_json_safe` only ever touches a
  non-finite float, nothing else), so every existing 422 keeps its exact
  same body. Deliberately didn't touch `Location` itself or add a
  NaN-specific validator there -- the bug was never in which values
  `Location` accepts (it was already correctly rejecting NaN/Infinity
  before this fix, same as `lat=999`), it was in the one path that reports
  *any* rejection crashing specifically when the rejected value happens to
  be NaN/Infinity, which is a FastAPI/Starlette response-building concern,
  not a schema one -- and the same fix, applied once at the app level,
  closes it for both this module's `Location` and the dispatch module's
  own separate copy without duplicating anything in either.
- Tests: new `tests/test_main.py` adds `test_json_safe_leaves_ordinary_
  values_untouched` and `test_json_safe_replaces_nan_and_infinity_with_
  their_str_at_any_depth` directly against the new helper, plus
  `test_create_request_rejects_a_nan_coordinate_instead_of_crashing_the_
  response` and `test_create_request_rejects_an_infinite_coordinate_
  instead_of_crashing_the_response`, the real end-to-end reproductions
  above through `POST /requests`. `tests/test_dispatch_api.py` adds
  `test_match_rejects_nan_coordinate_instead_of_crashing_the_response`,
  the same reproduction through `POST /match`. Ran all of these against
  the pre-fix code first (temporarily stashing just `app/main.py`) to
  confirm they actually fail there -- `test_main.py` fails to even import
  (`_json_safe` doesn't exist pre-fix at all) and the dispatch test
  reproduces the real `ValueError: Out of range float values are not JSON
  compliant` from inside Starlette's own response rendering, not just that
  they pass now. Full suite: 211 tests, up from 206, all green.

### 54. Stop a wall-clock-dependent test from going from green to red on its own, with no code change in between
- Not a numbered "Up next" item -- "Up next" only has tasks 13/19 on it and
  both are manual-only, so this morning run started the same way the last
  several did: set up a venv, installed requirements, and ran the full
  suite before going looking for a bug to fix. It didn't need to go
  looking -- `pytest` itself came back red, for real, on the very first
  run, no code change of mine involved at all.
- The one failure was
  `test_on_new_request_matches_a_recurring_rider_against_next_weeks_one_off_occurrence`,
  task 48's own regression test for the "recurring schedule expands to a
  date in the past" bug. That test pins `scoring.date.today()` to a fixed,
  hardcoded Thursday (`_FixedDate`, 2026-11-19) via monkeypatch, so
  `expand_schedule()`'s "next Monday" math always lands on the same fixed
  calendar date (2026-11-23) instead of whatever Monday happens to be
  upcoming on the day the suite actually runs -- exactly the point of
  pinning it. But `on_new_request()` also calls `is_expired()`, which
  reads `now` from `scoring.datetime.utcnow()` -- the real wall clock, not
  patched by this test at all. For as long as the real date stayed before
  2026-11-23, that real `now` was always earlier than the one_off_rider's
  2026-11-23T09:20 window regardless, so the gap between "date pinned" and
  "time not pinned" was invisible. It stopped being invisible the moment
  the real date became 2026-11-23 itself: `is_expired()` started reading
  the test's own one-off window as already expired, purely depending on
  what time of day the suite happened to run, and `on_new_request()`
  returned zero matches instead of one -- not a bug in the matching engine
  or in task 48's own fix, just a test that pinned half of "now" and
  trusted the other half to stay out of the way forever.
- Fix: a new `_FixedDateTime(datetime)` in `tests/test_engine.py`, pinned
  to the same Thursday `_FixedDate` already describes (2026-11-19) at a
  fixed hour (08:00) well before the Monday window the test builds from
  it, with its own `utcnow()` overridden the same way `_FixedDate.today()`
  already is. The test now monkeypatches `scoring_module.datetime` to this
  class alongside `scoring_module.date` -- freezing both halves of "now"
  `on_new_request()` actually reads, so the test no longer depends on
  either what day or what time of day it's actually run.
- Didn't touch `app/matching/scoring.py`, `app/matching/engine.py`, or
  task 48's own fix -- confirmed the regression was entirely in how this
  one test pinned time, not in the production code it exercises, by
  reading `expand_schedule()`/`is_expired()` fresh against this failure
  before changing anything. Ran the full suite against the unmodified
  test first to see it fail for real (`0 == 1`, the same
  `assert len(matches) == 1` task 48's own entry describes), then again
  after this fix to confirm it's deterministic now, not just incidentally
  passing on today's particular date/time. Full suite: 206 tests, same
  count as before (this fixes an existing test, it doesn't add one),
  all green.

### 53. Close the match-commit race task 51 flagged but didn't fix, with an atomic pair write
- Not a numbered "Up next" item -- "Up next" only has tasks 13/19 on it and
  both are manual-only, so this morning run went looking for a real bug the
  same way the last several runs did, and found the exact gap task 51's own
  note already flagged as real but left alone: "the engine side has the
  identical shape of gap... but fixing it needs a real design decision this
  task doesn't need to make." Looking at it directly, it turned out not to
  need a new design decision at all -- the unwind logic it needs is the same
  shape `on_new_request()` already has twice, just extended one step
  further.
- `on_new_request()` already rechecks both sides of a pending match against
  the store right before committing, to catch a concurrent cancel landing
  mid-scoring (task 49's own fix). But after both rechecks pass, it used to
  do the actual commit as two separate `store.save()` calls -- and "recheck,
  then write" always leaves some nonzero gap between the recheck returning
  and the write landing, the exact same shape task 51 closed for
  `cancel_request()` with `save_if_open()`'s single atomic UPDATE. Nothing
  had closed the mirror-image version of that gap on the engine's own
  commit side. Confirmed real, not theoretical, with a live script before
  writing any fix: paused `on_new_request()` right after its own
  `matched_at = datetime.utcnow()` call (the first thing it does once both
  rechecks have passed) via a monkeypatched `datetime`, ran the real
  `cancel_request()` sequence against the pooled candidate from a
  concurrent thread in that exact gap (a genuine, committed cancel), then
  let `on_new_request()` resume into its two old `save()` calls -- it still
  wrote MATCHED over the real cancel for both sides, silently reverting a
  cancel the poster already got a 200 for, and then crashed with an
  unhandled `ValueError: list.remove(x): x not in list`, since
  `cancel_request()`'s own `remove_from_pool()` had already dropped the
  candidate the engine still expected to find sitting in `self._unmatched`.
- Fix: a new `RequestStore.save_pair_if_both_open()` (`app/store.py`,
  `save_if_open()`'s own counterpart for a pair) runs both sides' condi-
  tional `UPDATE ... WHERE status = 'open'` in one transaction, committing
  only if *both* affected a row and rolling back -- so neither write takes
  effect -- if either didn't. `on_new_request()`'s final commit step now
  calls this once instead of two separate `save()`s, and if it returns
  `False`, unwinds exactly the way its own two earlier rechecks already do
  for the version of this race they catch: `best_candidate` is untouched in
  `self._unmatched` (it's only ever removed on confirmed success), so the
  side that's still genuinely OPEN needs no action; the side that got
  cancelled is dropped from the pool instead of left there forever; and
  `request` itself (never pooled either way) only rejoins the pool if it's
  still open and still matchable (`can_ever_be_matched()`, same as every
  other place this engine decides whether pooling something is worth doing
  at all). Deliberately left `match_batch()` alone -- it has the identical
  shape of race in principle, but nothing in this codebase actually calls
  it outside tests (`run_forever()`/`on_new_request()` is the only path a
  real request ever goes through), so there's no live exposure to close
  there the way there was here.
- Tests: `tests/test_store_persistence.py` adds
  `test_save_pair_if_both_open_writes_both_and_returns_true_when_both_are_still_open`
  and
  `test_save_pair_if_both_open_writes_neither_and_returns_false_when_either_is_not_open`
  (the latter: one side already cancelled by a separate real writer, both
  sides' stored rows confirmed untouched afterward, not just the cancelled
  one). `tests/test_engine.py` adds
  `test_on_new_request_does_not_revert_a_cancel_that_lands_right_before_its_own_write`,
  the exact reproduction above through the real `on_new_request()`, pausing
  right after its `matched_at` timestamp instead of mid-scoring the way
  task 49's two existing race tests do (they cover an earlier part of the
  same race; this one covers the sliver neither of them reaches). Ran all
  three against the pre-fix code first (temporarily stashing
  `app/store.py`/`app/matching/engine.py`) to confirm they actually fail
  there -- the engine test reproduced the exact unhandled `ValueError`
  described above, not just a wrong return value, and the two store tests
  fail with `AttributeError` since `save_pair_if_both_open` doesn't exist
  pre-fix at all. Full suite: 206 tests, up from 203, all green.

### 52. Stop a Nominatim HTTP failure from 500ing GET /geocode instead of a clean 503
- Not a numbered "Up next" item -- "Up next" only has tasks 13/19 on it and
  both are manual-only, so this evening run went looking for a real bug the
  same way the last several runs did, and found the other half of task 45's
  own gap in `app/geocoding.py`/`app/router.py` -- that one was about a
  malformed JSON *payload* from Nominatim, this one's about Nominatim's
  *HTTP transport* itself (a bad status, a timeout, a dropped connection).
- `geocode_place()` deliberately lets a real HTTP failure from Nominatim
  propagate as a raw `httpx` exception instead of swallowing it into a
  silently wrong match -- that's an intentional, already-tested decision
  (`tests/test_geocoding.py`'s
  `test_geocode_place_propagates_http_errors_instead_of_a_silent_wrong_match`),
  and I didn't touch it. But `GET /geocode` (`app/router.py`) only ever
  caught `PlaceNotFoundError` -- so that propagated exception had nowhere
  to land. Confirmed this was real, not theoretical, with a live
  `TestClient` call before writing any fix: mocking a Nominatim `503`
  response, and separately a connection timeout, both came back through
  the real `GET /geocode` route as a bare, unhandled `500` -- identical to
  an actual server bug, with nothing telling a caller "the geocoding
  service is temporarily unavailable, try again" apart from "that place
  doesn't exist here." Nominatim is a free, rate-limited third-party
  service with no SLA (this same module's own
  `MIN_SECONDS_BETWEEN_REQUESTS` rate limiter already treats it that way),
  so a transient `429`/`503` or timeout is a real, expected production
  failure mode, not a hypothetical one -- and this sandbox's own network
  policy denying the real Nominatim host outright (per task 10/45's own
  notes) means this exact gap could never have shown up by just running
  the app here and trying it, only by deliberately reproducing the failure.
- Fix: `GET /geocode` now also catches `httpx.HTTPError` (the common base
  for both `HTTPStatusError`, from `raise_for_status()`, and a transport
  failure like `TimeoutException`/`ConnectError`) and turns it into a
  clean `503` with a clear "temporarily unavailable" message, instead of
  letting it fall through as an unhandled `500`. No change to
  `geocode_place()` itself -- it still propagates exactly as before and
  the existing test proving that stays green; this only adds the one
  router-level boundary that was missing.
- Tests: `tests/test_geocoding.py` adds
  `test_geocode_endpoint_503s_instead_of_a_raw_500_on_a_nominatim_error_status`
  and `test_geocode_endpoint_503s_instead_of_a_raw_500_on_a_nominatim_timeout`
  (both reproductions above, through the real `GET /geocode` route). Ran
  both against the pre-fix code first (temporarily stashing just
  `app/router.py`) to confirm they actually fail there -- a real unhandled
  `httpx.ConnectTimeout`/`HTTPStatusError` surfacing out of the test
  client, not just that they pass now. Full suite: 203 tests, up from 201,
  all green.

### 51. Close the race task 49's "recheck right before writing" fix only narrowed, with an atomic conditional write
- Not a numbered "Up next" item -- "Up next" only has tasks 13/19 on it and
  both are manual-only, so this morning run went looking for a real bug the
  same way the last several runs did, and found that task 49's own fix
  (two runs ago) hadn't actually closed the race it set out to close -- it
  had narrowed it.
- Task 49 made `cancel_request()` (`app/router.py`) re-read and re-check the
  store a second time, right before writing CANCELLED, to guard against a
  real match landing in the gap between its first read and its write. But
  "recheck right before writing" is still a separate read followed by a
  separate write -- there's always *some* nonzero gap between that second
  recheck's own read returning and the write actually committing, and a
  concurrent match can land in that gap too, just a much smaller one than
  before. Confirmed this was real, not theoretical, with a live script
  before writing any fix: paused `cancel_request()` at the very last
  moment before its own write (its `datetime.utcnow()` call for
  `status_changed_at`, immediately before the old `store.save()`), ran a
  real `on_new_request()` match against the exact same request from a
  concurrent thread right there, then let the stale cancel resume into its
  write -- it still came back a real `200`/`cancelled`, silently
  overwriting the match and wiping `matched_with` back to `None`, while
  the matched counterpart's own row still pointed back at it as MATCHED.
  Same bug task 49 described, just moved to a narrower window task 49's
  own fix never actually eliminated -- no amount of rechecking *before*
  the write closes a gap that exists *because* the check and the write are
  two separate operations.
- Fix: a new `RequestStore.save_if_open()` (`app/store.py`) that does the
  whole thing -- check and write -- as a single conditional SQL statement,
  `UPDATE ride_requests SET ... WHERE id = :id AND status = 'open'`,
  instead of a read followed by a write. Postgres's own row-level locking
  serializes two concurrent writers against the same row: whichever one
  commits second has its `WHERE status = 'open'` evaluated against the
  first one's already-committed row, not against whatever either side
  read before either one wrote -- there's no gap left for a third write to
  land in, because there's only one statement. Returns whether the write
  actually took effect (`rowcount > 0`), so the caller can tell a real
  cancel from one that lost the race. `cancel_request()` now does a single
  read+check up front (for a fast, friendly 404/409 on the common,
  non-racy path) and then calls `save_if_open()` for the actual write --
  on a lost race, it re-reads once more purely to report an accurate
  status in the 409, not as a guard; `save_if_open()`'s own `WHERE` clause
  is the only thing that actually decides whether the cancel happened.
  Deliberately didn't touch `RequestStore.save()` itself (still a blind
  overwrite) or its other two call sites (`app/matching/engine.py`'s own
  match-time writes) -- `save()` is still exactly what a handful of tests
  and the engine's own match path intentionally rely on, and the engine
  side has the identical shape of gap (its own two "recheck before
  writing" guards have the same narrowing-not-closing problem this fix
  just described) but fixing it needs a real design decision this task
  doesn't need to make to close the one race actually confirmed live:
  what should `on_new_request()` do with its already-mutated in-memory
  `request`/`best_candidate` objects and the pool state it's already
  changed (`self._unmatched.remove(best_candidate)`) if its own atomic
  write loses the race -- unwind all of it and report no match, or
  something else? Left as a flagged gap, not guessed at here, the same
  way this file flags other open design questions rather than resolving
  them by assumption.
- Tests: `tests/test_store_persistence.py` adds
  `test_save_if_open_writes_and_returns_true_when_the_stored_row_is_still_open`
  and
  `test_save_if_open_does_not_write_and_returns_false_when_the_stored_row_is_not_open`
  directly against the new method. `tests/test_requests_api.py` adds
  `test_cancel_does_not_revert_a_match_that_lands_right_before_its_own_write`,
  the exact reproduction above (pausing at the last instant before the
  write, not just after the first read the way task 49's own test does),
  asserting the cancel 409s and the real match stays intact. Ran the new
  `test_requests_api.py` test against the pre-fix code first (temporarily
  stashing `app/router.py`/`app/store.py`) to confirm it actually fails
  there -- a real `200`/`cancelled` response overwriting a genuine match,
  not just that it passes now; task 49's own existing regression test
  still passes unchanged against the new code. Full suite: 201 tests, up
  from 198, all green.

### 50. Stop a near-year-1/year-9999 departure time from crashing fuzz_schedule() with a bare OverflowError
- Not a numbered "Up next" item -- "Up next" only has tasks 13/19 on it and
  both are manual-only, so this morning run went looking for a real bug the
  same way the last several runs did, and found one in `app/privacy.py`'s
  `fuzz_schedule()` -- a datetime-arithmetic crash, not the validation
  gaps or race conditions most of the recent entries here were.
- Nothing in `OneOffSchedule`'s own validator (`app/schemas.py`) bounds how
  far in the past or future `earliest_departure`/`latest_departure` can be
  -- it only checks the two fields are naive (timezone-free) and correctly
  ordered. That leaves a real, reachable input nothing stops: a schedule
  within `FUZZ_PADDING` (15 minutes) of either end of the datetime range
  Python can even represent (year 1 or year 9999 -- plausible from a
  4-digit-year typo on a non-browser client, e.g. "0001" instead of
  "2026," same as any other field-mistype this form already guards
  against elsewhere). Confirmed this was real, not theoretical, with a
  live `TestClient` call before writing any fix: `POST /requests` with
  `earliest_departure="0001-01-01T00:05:00"` validated cleanly through
  `OneOffSchedule`'s own checks and then raised a bare `OverflowError:
  date value out of range` from `fuzz_schedule()`'s own `schedule.
  earliest_departure - FUZZ_PADDING` -- and it crashed on the *same* `POST
  /requests` call that created the request, not some later read, since
  `create_request()` (`app/router.py`) already calls `to_public()` ->
  this function for its own response. Worse, once such a row exists and
  stays open, `GET /requests`/`GET /browse` call the same
  `to_list_item()`/`to_public()` path for *every* open request on every
  call -- so one bad row kept crashing the public listing for every
  caller, not just the poster who triggered it.
- Fix: a new `_shift_datetime()` helper, the `OneOffSchedule` counterpart
  to this same function's existing `_shift_time()` (which already clamps
  a `RecurringSchedule`'s time-of-day fields at midnight instead of
  wrapping, for the exact same "don't let the shift produce something
  unrepresentable" reason) -- it widens a datetime by `FUZZ_PADDING` and
  clamps to `datetime.min`/`datetime.max` on overflow instead of letting
  the arithmetic raise. `fuzz_schedule()`'s `OneOffSchedule` branch now
  calls it instead of doing the add/subtract inline. Deliberately doesn't
  add a new bound to `OneOffSchedule` itself to reject an extreme date at
  intake -- unlike the Postgres-column-limit fixes (seats_needed, NUL
  bytes), there's no actual storage limit being violated here; Postgres'
  `DateTime` column and Python's own `datetime` already agree on the same
  year 1-9999 range, so rejecting it would be inventing a new product
  rule about how far out a trip can be scheduled that nothing in
  SCOPE.md/TASKS.md calls for. This just stops the one function that
  actually crashes from crashing.
- Tests: `tests/test_privacy.py` adds
  `test_fuzz_schedule_clamps_one_off_window_at_the_datetime_range_instead_of_overflowing`
  (both ends, directly against `fuzz_schedule()`). `tests/test_requests_api.py`
  adds the HTTP-level reproduction,
  `test_create_request_near_the_edge_of_the_datetime_range_does_not_500_on_its_own_response`
  -- the exact year-1 payload above now `201`s, and a following `GET
  /requests` stays `200` instead of crashing. Ran both against the
  pre-fix code first (temporarily stashing just `app/privacy.py`) to
  confirm they actually fail there -- a real `500`/uncaught
  `OverflowError`, not just that they pass now. Full suite: 198 tests, up
  from 196, all green.

### 49. Stop a concurrent match from being silently overwritten by a stale cancel
- Not a numbered "Up next" item -- "Up next" only has tasks 13/19 on it and
  both are manual-only, so this evening run went looking for a real bug the
  same way the last several runs did, and found the missing other half of
  the exact race class tasks 44-47's own engine-side rechecks already cover
  -- this one's in `cancel_request()` (`app/router.py`) itself, which never
  got the symmetric fix.
- `on_new_request()` already rechecks the store right before finalizing a
  match, specifically to guard against a concurrent cancel landing on
  either side of the pair mid-scoring (see its own two "store-backed race"
  comments). But I never applied the mirror-image guard to
  `cancel_request()`: it reads the target once at the top, checks its
  status, and writes `CANCELLED` using that same, now-possibly-stale
  object -- with nothing re-checking in between. `cancel_request()` is a
  sync route, which Starlette dispatches to a threadpool worker, not the
  asyncio event loop `run_forever()`/`on_new_request()` run on, so a real
  match for the exact request being cancelled can land in that gap. Caught
  this live, not theoretically, with a script before writing any fix:
  captured `cancel_request()`'s own first read of an OPEN, pooled request,
  ran the real `on_new_request()` against it concurrently (a genuine
  match, flipping its stored status to MATCHED and handing the
  counterpart a real reveal), then resumed the stale cancel with that
  pre-match read -- the DB came back CANCELLED with `matched_with` wiped
  to None, silently erasing the match, while the counterpart's own row
  still pointed back at it as MATCHED. Anyone relying on that match (the
  counterpart's live WebSocket reveal, or a later `GET
  /requests/{id}?viewer_request_id=`) would've been left looking at a
  stranger's now-broken, contradictory pair of rows.
- Fix: `cancel_request()` now re-fetches and re-checks the request's
  computed status a second time, immediately before writing the
  cancellation, using that fresh read (not the original one) for the
  write -- the same "recheck right at the point of no return" pattern
  `on_new_request()` already uses, just applied from the other side. If a
  match landed in the gap, this second check now sees MATCHED and 409s
  instead of overwriting it.
- Tests: `tests/test_requests_api.py` adds
  `test_cancel_does_not_revert_a_match_that_landed_between_its_read_and_its_write`,
  calling the real `cancel_request()` directly (not through TestClient, so
  the interleaving is deterministic) with a monkeypatched `to_public` that
  pauses after the function's first read, runs a real `on_new_request()`
  match against the exact same request while paused, then resumes --
  asserting the cancel 409s and both sides of the match are still intact
  in the store afterward. Ran it against the pre-fix code first
  (temporarily stashing just `app/router.py`) to confirm it actually fails
  there -- a real `200`/`cancelled` with `matched_with` wiped, not just
  that it passes now. Full suite: 196 tests, up from 195, all green.

### 48. Fix expand_schedule() anchoring a recurring weekday to the past instead of its next real occurrence
- Not a numbered "Up next" item -- "Up next" only has tasks 13/19 on it and
  both are manual-only, so this morning run went looking for a real bug
  the same way the last several runs did, and found one in
  `app/matching/scoring.py`'s `expand_schedule()` -- a date-math bug in how
  a `RecurringSchedule` gets turned into concrete windows for scoring, not
  a validation gap or a leak the way most of the recent entries here were.
- `expand_schedule()` turned each weekday in `schedule.weekdays` into a
  date inside the Monday-Sunday week *containing* `reference_date` (today,
  by default) -- not that weekday's actual next occurrence. For any
  weekday earlier in the week than today, that's a date in the past: from
  a real Thursday, `weekdays=[0]` (Monday) expanded to the Monday *3 days
  before* today, not the upcoming one. That's invisible comparing two
  `RecurringSchedule`s against each other (both expand with the same
  default `reference_date`, so they agree on the same wrong date for a
  shared weekday, and the overlap check never notices). But a
  `RecurringSchedule` scored against a `OneOffSchedule` compares real
  calendar dates, and a one-off rider's date is whatever actual future day
  they typed -- unrelated to "today's own week." SCOPE.md's whole point
  for recurring requests is a standing commute matching against whoever
  else is going that way, one-off riders very much included, so this
  wasn't a corner case. Confirmed real, not theoretical, with a live
  script before writing any fix: from a real Thursday, a recurring rider
  posting "every Monday, 9:00-9:30" and a one-off rider posting the very
  next Monday, 9:05-9:20, same origin/destination -- a textbook
  same-corridor, overlapping-window match on every other dimension --
  never matched through the real engine: the recurring side expanded to a
  Monday 3 days in the past, the one-off side had the real upcoming
  Monday, `temporal_score()` saw two different calendar dates and scored
  0.0 overlap, and both requests sat in `on_new_request()`'s pool
  unmatched afterward.
- Fix: `expand_schedule()` now walks forward from `reference_date` to each
  weekday's next occurrence on or after it (`days_ahead = (weekday -
  reference_date.weekday()) % 7`), instead of locating that weekday inside
  `reference_date`'s own Monday-Sunday week. Still anchors every weekday to
  the same `reference_date` for any pair of schedules expanded in the same
  scoring pass, so `RecurringSchedule`-vs-`RecurringSchedule` stays exactly
  as comparable as before (both still land on the same date for a shared
  weekday) -- it just never produces a date earlier than `reference_date`
  itself anymore, which is what makes it line up correctly against a real
  `OneOffSchedule` date too. Deliberately narrow: doesn't touch the
  separate, already-flagged "does today's occurrence expire once its own
  time passes" question (docs/MATCHING_ALGORITHM.md's "Request lifecycle"
  section already calls that a real redesign, not attempted here) -- this
  is purely about which calendar date each weekday maps to, not when a
  recurring request should stop being matchable.
- Tests: `tests/test_scoring.py` adds
  `test_expand_schedule_recurring_never_lands_on_a_date_before_reference_date`
  (the exact Thursday/Monday reproduction above, pinned to a fixed date so
  it doesn't depend on which real day the suite runs),
  `test_expand_schedule_recurring_keeps_todays_own_weekday_on_reference_date`
  (today's own weekday still expands to today, unaffected), and
  `test_expand_schedule_recurring_multiple_weekdays_still_span_less_than_a_week`
  (the existing "all instances within one week of each other" invariant
  still holds under the new next-occurrence math). `tests/test_engine.py`
  adds
  `test_on_new_request_matches_a_recurring_rider_against_next_weeks_one_off_occurrence`,
  the real end-to-end reproduction above through the actual engine, with
  "today" pinned via monkeypatching `app.matching.scoring.date` to the
  same real Thursday. Ran all four against the pre-fix code first
  (temporarily stashing just `app/matching/scoring.py`) to confirm they
  actually fail there -- the engine test came back with zero matches, not
  one, and two of the three `expand_schedule()` unit tests failed on the
  wrong date, not just that they pass now. Full suite: 195 tests, up from
  191, all green.

### 47. Stop a request no partner could ever fit from sitting in the matching pool forever
- Not a numbered "Up next" item -- "Up next" only has tasks 13/19 on it and
  both are manual-only, so this evening run went looking for a real bug the
  same way the last several runs did, and found the same unbounded-pool
  shape task 44 already fixed once, just with a different trigger that
  task 44's own fix doesn't reach.
- Task 44 fixed `on_new_request()` leaving an *expired* pool member in
  `self._unmatched` forever. But `capacity_fits()` only depends on the two
  requests' `seats_needed` -- never location or time -- and the smallest
  possible partner is `seats_needed=1` (`app/schemas.py`'s `Field(ge=1)`).
  That means a request whose own `seats_needed` already equals or exceeds
  `DEFAULT_VEHICLE_CAPACITY` (4) can never satisfy `capacity_fits()` with
  *any* partner, no matter how perfect every other dimension is or how
  long it waits -- a real, reachable case, not a contrived one: SCOPE.md's
  own "a friend posting on behalf of a couple of others" example, taken to
  the vehicle's own limit, is exactly a party that fills the whole car
  alone. Nothing anywhere ever checked "could this request even in
  principle match somebody" before pooling it, so it got pooled on arrival
  like any other unmatched request -- and if it's a `RecurringSchedule`
  (SCOPE.md: "recurring requests are first-class," e.g. "daily commute for
  me and 3 friends"), task 44's own expiry prune can't reach it either,
  since `scoring.is_expired()` always returns `False` for a recurring
  schedule -- there's no window to pass. Confirmed this was real, not
  theoretical, with a live script before writing any fix: posted one
  recurring request with `seats_needed == DEFAULT_VEHICLE_CAPACITY`, then
  ran 50 unrelated, mutually-compatible requests through the same engine
  one at a time -- every one of those 50 paired off and left the pool
  normally, but the `seats_needed=4` request was still sitting in
  `self._unmatched` afterward, confirmed never touched, and nothing
  anywhere would ever touch it: unlike an expired one-off request, this
  one has no window to wait out, so it's not a temporary wait, it's
  permanent for as long as the process runs -- one more entry added to
  `self._unmatched` (and the bucketing index rebuilt from it on every
  single incremental call) per such request, forever, for exactly the
  real ~1,000-person deployment SCOPE.md describes.
- Fix: a new `can_ever_be_matched()` (`app/matching/scoring.py`, next to
  `capacity_fits()` it depends on) checks a request's own `seats_needed`
  against the smallest theoretically possible partner
  (`MIN_PARTNER_SEATS = 1`) -- not against whichever candidates happen to
  be bucketed nearby right now, since `capacity_fits()` never depends on
  location/time anyway, so "fails against the smallest possible partner"
  really does mean "fails against every possible partner, permanently."
  `on_new_request()` now uses it in two places, mirroring task 44's own
  two-sided fix exactly: the top-of-call prune that already drops expired
  members now also drops capacity-impossible ones, and the "no candidate
  found, so pool it" branch no longer pools a request that could never be
  matched in the first place -- it still returns `[]` (still a real, open,
  visible request via `GET /requests`/`/mine/{id}`, exactly as before),
  it's just never added to the *internal* pool, which is invisible to
  every public response anyway. Deliberately narrow: this changes nothing
  about matching outcomes (such a request could never have won a match
  regardless, by `capacity_fits()`'s own symmetric logic -- it fails
  against this request from the *other* side too, so it was never a
  realizable candidate for anyone else either), only what the pool holds
  onto uselessly.
- Tests: `tests/test_scoring.py` adds
  `test_can_ever_be_matched_true_exactly_when_the_smallest_possible_partner_fits`
  (the boundary itself: true for seats_needed 1-3, false for 4-5, against
  `vehicle_capacity=4`). `tests/test_engine.py` adds
  `test_on_new_request_does_not_pool_a_request_no_partner_could_ever_fit`
  (the exact reproduction above, via `on_new_request()` directly) and
  `test_on_new_request_purges_a_capacity_impossible_pool_member_instead_of_leaving_it_forever`
  (same shape as task 44's own pool-purge test -- a member already sitting
  in the pool gets swept by the same prune, not just kept out on its own
  way in). Ran both new `test_engine.py` tests against the pre-fix code
  first (temporarily stashing `app/matching/engine.py`/`scoring.py`) to
  confirm they actually fail there -- the request was still sitting in
  `self._unmatched` in both cases, not just that they pass now; the new
  `test_scoring.py` test fails to even import pre-fix, since
  `can_ever_be_matched` doesn't exist yet. Full suite: 191 tests, up from
  188, all green.

### 46. Stop a non-numeric `seats_needed`/`weekdays` on the `/new` form from 422ing with raw JSON instead of the form's own error page
- Not a numbered "Up next" item -- "Up next" only has tasks 13/19 on it and
  both are manual-only, so this morning run went looking for a real bug the
  same way the last several runs did, and found one in `app/web.py`'s
  `submit_new_request()` -- a gap in this form's own error handling, not in
  the matching engine/race-condition territory most of the last several
  entries lived in.
- Every other bad value this form can receive -- a place name that doesn't
  geocode, a bad schedule, an empty `rider_id`/`contact` -- gets caught by
  this function's own `try`/`except` and re-rendered as the same form page
  with a clear "Couldn't post that request: ..." message and whatever the
  rider already typed still filled in, per this function's own comment
  ("so a mistake doesn't mean starting the form over from scratch"). But
  `seats_needed` was typed `int = Form(1)` and `weekdays` was typed
  `list[int] = Form([])` directly on the route signature -- which means
  FastAPI/pydantic coerces them to `int` *before* `submit_new_request()`
  ever runs at all, so a bad value in either one never reaches this
  function's own error handling, or its own form page, no matter what.
  Confirmed this was real, not theoretical, with a live `TestClient` call
  before writing any fix: `POST /new` with `seats_needed="abc"` (a rider
  mistyping the seats field, or any non-browser client) returned a bare
  `{"detail":[{"type":"int_parsing","loc":["body","seats_needed"],...}]}`
  JSON body, not this form's own page -- and `weekdays=["abc"]` on a
  recurring submission 422'd the exact same way. A browser's own
  `type="number"`/fixed checkbox values mostly keep a normal user from
  typing this by hand, but nothing about this form is only reachable from
  a browser (SCOPE.md never says the API is browser-only, and this is the
  same kind of "nothing stops a non-browser client" gap several of the
  last several entries here have found elsewhere), and even a browser can
  be made to submit a garbage value through devtools or a browser
  extension without the server ever noticing the difference.
- Fix: both fields now come in as plain strings (`seats_needed: str =
  Form("1")`, `weekdays: list[str] = Form([])`) and get parsed inside the
  existing `try` block, same pattern as `origin_lat`/`origin_lng`'s own
  `float()` calls right next to them -- a parse failure now raises the
  same `ValueError` the existing `except (ValidationError, ValueError,
  TypeError)` already catches, routing it through the one error path this
  endpoint already has instead of a second, inconsistent one FastAPI
  provides for free. A blank `seats_needed` (a genuinely cleared number
  field, not a mistyped one) still defaults to `1`, the same behavior the
  old `int = Form(1)` typing gave it for free -- this fix closes the
  "non-numeric input 422s with the wrong error" gap without changing what
  a blank field does. `new_request.html`'s weekday-checkbox re-check
  (`day in form.weekdays`) had to change to `day|string in form.weekdays`
  to match `weekdays`'s new string-typed form state -- otherwise a
  recurring submission that failed for an unrelated reason (e.g. a bad
  geocode) would silently lose its previously-checked weekday boxes on
  the re-rendered form, even though the actual fix above was unrelated to
  that behavior.
- Tests: `tests/test_web_frontend.py` adds
  `test_non_numeric_seats_needed_reprompts_form_instead_of_a_raw_422` and
  `test_non_numeric_weekday_reprompts_form_instead_of_a_raw_422` (the exact
  two reproductions above, each asserting a `400` HTML re-render instead
  of a `422` JSON body), `test_blank_seats_needed_still_defaults_to_one`
  (proving the blank-field behavior didn't regress), and
  `test_recurring_form_recheck_shows_the_right_weekday_boxes_after_an_unrelated_error`
  (the checkbox-recheck fix, triggered by an unrelated bad-geocode error).
  Ran the two reproduction tests against the pre-fix code first (temporarily
  stashing `app/web.py`/`new_request.html`) to confirm they actually fail
  there -- a real `422` with FastAPI's raw JSON body, not the `400` HTML
  page, on both -- not just that they pass now. Full suite: 188 tests, up
  from 184, all green.

### 45. Stop a malformed Nominatim result from 500ing `GET /geocode` instead of a clean 404
- Not a numbered "Up next" item -- "Up next" only has tasks 13/19 on it and
  both are manual-only, so this evening run went looking for a real bug the
  same way the last several runs did, and found one in `app/geocoding.py`'s
  `geocode_place()` -- its own handling of what Nominatim actually hands
  back, not the rate limiter or request-shaping the last geocoding-related
  entry (task 30) touched.
- `geocode_place()`'s own docstring promises "raise PlaceNotFoundError --
  never returns a guessed/default location," and `GET /geocode`
  (`app/router.py`) only catches that one exception type, turning it into a
  clean 404. But the final line builds `Location(lat=float(top["lat"]),
  lng=float(top["lon"]))` straight from whatever Nominatim's JSON response
  happened to contain, with nothing guarding either conversion. This
  sandbox's network policy denies the real nominatim.openstreetmap.org
  outright (this module's own docstring already notes that), so every test
  here has always mocked the HTTP response -- which is exactly why a result
  shaped unexpectedly (a non-numeric "lat"/"lon" string, or a coordinate
  genuinely out of range) never got exercised: nothing about trusting
  upstream JSON blindly is specific to being unable to reach the real
  service, it's just the gap this sandbox's own test setup happened to
  leave uncovered. Confirmed this was real, not theoretical, with a live
  script before writing any fix: a mocked response of `{"lat": "999.0",
  "lon": "-500.0"}` crashed `geocode_place()` with a bare
  `pydantic_core.ValidationError` (out of `Location`'s own -90..90/-180..180
  range checks), and `{"lat": "not-a-number", "lon": "-77.3"}` crashed it
  with a bare `ValueError` from `float()` -- neither is a
  `PlaceNotFoundError`, so both would reach a real caller of `GET /geocode`
  as an unhandled 500, not the clear 404 this endpoint's own docstring
  describes for exactly this situation ("never a guessed location").
- Fix: the `Location(...)` construction is now wrapped in a `try`/`except
  (KeyError, TypeError, ValueError)` (pydantic's `ValidationError` is itself
  a `ValueError` subclass, so one clause catches both failure shapes) that
  re-raises as `PlaceNotFoundError` -- the same exception, and the same
  caller-facing contract, this function already uses for "Nominatim found
  nothing." No change to `app/router.py`: it already catches
  `PlaceNotFoundError` and turns it into a 404, so this closes the gap at
  the one place that actually produces the bad data instead of teaching the
  router a second exception type to catch.
- Tests: `tests/test_geocoding.py` adds
  `test_geocode_place_raises_clear_error_on_an_out_of_range_coordinate` and
  `test_geocode_place_raises_clear_error_on_a_non_numeric_coordinate`, the
  exact two reproductions above, each asserting `PlaceNotFoundError` instead
  of a crash. Ran both against the pre-fix code first (temporarily stashing
  just `app/geocoding.py`) to confirm they actually fail there -- a real
  `ValidationError`/`ValueError` surfaced, not just that they pass now.
  Full suite: 184 tests, up from 182, all green.

### 44. Stop an expired pool member from sitting in `self._unmatched` forever instead of actually leaving the pool
- Not a numbered "Up next" item -- "Up next" only has tasks 13/19 on it and
  both are manual-only, so this morning run went looking for a real bug the
  same way the last several runs did, and found one in
  `app/matching/engine.py`'s `on_new_request()` -- a resource leak this
  time, not a validation gap or a privacy leak the way most of the last
  dozen entries here were.
- `on_new_request()` already skips a pool member whose one-off window has
  passed by the time it's scored (`is_expired(candidate)`, right next to
  this fix) -- but skipping it as a *candidate* was all that ever
  happened. Nothing anywhere actually removes an expired request from
  `self._unmatched`: `remove_from_pool()` only runs on a real cancel, and
  `candidates_for()`'s H3 bucketing has no reason to ever revisit a cell
  with nothing left nearby. Left alone, every one-off request a real rider
  posts and never matches before its window passes -- which SCOPE.md's own
  ~1,000-person deployment makes routine, not rare -- just sits in that
  list for the rest of the process's life, and `build_indexes(self._unmatched)`
  (called fresh on every single incremental call) rebuilds its H3 index
  over that same, permanently-growing list every time. Confirmed this was
  real, not theoretical, with a live script before writing any fix: pooled
  a one-off request whose window was a second from passing (no candidate
  yet, so `on_new_request()` pooled it normally), let real wall-clock time
  carry it past that window, then ran a second, unrelated request through
  `on_new_request()` -- the first request was still sitting in
  `self._unmatched` afterward, confirmed expired, with nothing having ever
  touched it.
- Fix: `on_new_request()` now prunes every expired member out of
  `self._unmatched` at the top of the call, before it's used for anything
  -- a plain `is_expired()` filter, no new state, no separate cron/sweep
  job needed, same "compute it live, no background job" posture TASKS.md
  #14 already established for expiry elsewhere. The pool now only ever
  holds genuinely still-open, not-yet-expired requests, so its size tracks
  real outstanding demand instead of how long the process has been
  running.
- Tests: `tests/test_engine.py` adds
  `test_on_new_request_purges_an_expired_pool_member_instead_of_leaving_it_forever`,
  the exact reproduction above (a backdated pool member, a later unrelated
  arrival, asserting the expired one is actually gone from
  `self._unmatched` afterward) -- the existing
  `test_on_new_request_skips_a_candidate_that_expired_while_pooled` already
  proved an expired member can't *win*, but never checked whether it
  *stayed*. Ran the new test against the pre-fix code first (temporarily
  stashing just `app/matching/engine.py`) to confirm it actually fails
  there -- it does, the expired request was still in the pool -- not just
  that it passes now. Full suite: 182 tests, up from 181, all green.

### 43. Stop `GET /requests` from handing out the one id the post-match reveal treats as a secret
- Not a numbered "Up next" item -- "Up next" only has tasks 13/19 on it and
  both are manual-only, so this evening run went looking for a real bug the
  same way the last several runs did, and found a bigger version of the
  exact class of leak tasks 41/42 already closed on the WebSocket side --
  this one's in the plain JSON `GET /requests` endpoint, no websocket
  involved at all.
- `GET /requests/{id}?viewer_request_id=` (task 7) treats knowing a
  request's own id as the *only* proof needed to see its precise
  pickup/dropoff and contact once matched -- its own docstring calls the
  id "unguessable... and never displayed to anyone else." But
  `RideRequestPublic` (the shape `to_public()` built, `id` included) was
  also exactly what `GET /requests`' open list and `GET /browse` handed to
  literally anyone, no auth required (SCOPE.md: open-join, no SMS/OTP) --
  so every open request's id was sitting in plain sight before it was ever
  matched. Confirmed this was real, not theoretical, with a live script
  before writing any fix: posted two compatible riders, read both of their
  ids straight off a real `GET /requests` call made *before* they matched
  each other (nothing more than that one already-public GET), confirmed
  both ids vanished from that same list once they did (a free, public
  signal of who just matched whom), then called `GET
  /requests/{a}?viewer_request_id={b}` using nothing but that scraped pair
  -- and got back a `200` with a's full precise origin/destination and
  real contact info, as a caller with zero relationship to either request.
  Tasks 41/42 already closed this exact class of leak on the `/matches`
  WebSocket (every match's ids broadcast to every connection); this was
  the same leak's quieter, no-websocket-required sibling, reachable with
  two plain `GET` calls from anyone at any time.
- Fix: a new `RideRequestListItem` schema (`app/schemas.py`) -- the same
  coarse/fuzzed fields `RideRequestPublic` already had, minus `id` -- and
  a new `to_list_item()` (`app/privacy.py`, sharing the actual field-
  building logic with `to_public()` via a new `_coarse_fields()` helper).
  `GET /requests` (`app/router.py`) and `GET /browse` (`app/web.py`) now
  both build this id-less shape instead of `RideRequestPublic`.
  `RideRequestPublic` (id included) stays exactly as it was for the three
  places that are actually safe to hand an id back: `POST /requests`'s own
  response (the one legitimate, one-time hand-off of a brand-new id to its
  rightful owner), `POST /requests/{id}/cancel`'s response, and `GET
  /requests/{id}` (the id was already in the URL the caller used to get
  there). No caller anywhere in this codebase needed the id *from* the
  open list -- the poster already has their own from `POST /requests`, and
  the matched counterpart learns the other id from the `/matches`
  WebSocket event itself, already filtered to the two involved parties by
  tasks 41/42's own fix, not from this list either -- so this closes the
  hole without taking anything away from a real caller.
- Tests: `tests/test_requests_api.py` adds
  `test_list_requests_never_includes_the_request_id_either` (the plain
  "the field isn't there" check) and
  `test_scraping_the_open_list_before_a_match_can_no_longer_reveal_it_after`
  (the real end-to-end reproduction above -- scrape the list before a
  match, confirm nothing scraped can be used after). Also updated three
  existing tests that happened to correlate `GET /requests`' entries by
  `id` (now gone) to correlate by `rider_id` instead, since each already
  used a unique one. `tests/test_privacy.py` adds
  `test_to_list_item_never_includes_id_contact_or_precise_location`
  directly against `to_list_item()`. Ran the two new `test_requests_api.py`
  tests against the pre-fix code first (temporarily stashing
  `app/privacy.py`/`app/router.py`/`app/schemas.py`/`app/web.py`) to
  confirm they actually fail there -- a real scraped id that both matches
  and successfully reveals the full record, not just that they pass now.
  Full suite: 181 tests, up from 178, all green.

### 42. Close a `/matches` connection that never registers instead of leaking it (and its queue) forever
- Not a numbered "Up next" item -- "Up next" only has tasks 13/19 on it and
  both are manual-only, so this morning run went looking for a real bug the
  same way the last several runs did, and found one right next to task 41's
  own fix in `stream_matches()` -- not a privacy leak this time, a resource
  leak in the registration step that fix added.
- Task 41 made `stream_matches()` wait for a connection's first message (its
  own `request_id`) before forwarding it anything, closing a real privacy
  hole. But that wait, `await websocket.receive_json()`, had no timeout --
  and `engine.subscribe()` runs *before* it, on purpose, so the connection
  is already a real subscriber, with a real queue, the moment it opens, long
  before it ever registers. SCOPE.md's open-join/no-auth model means nothing
  stops any client -- not just a browser running `live.js`, which does send
  its id immediately -- from opening this endpoint with a bare WebSocket
  client and simply never sending anything. For as long as that connection
  stays open, every match anyone else makes gets `put()` onto its queue by
  `run_forever()` same as any other subscriber's, but nothing ever reaches
  the `queue.get()` loop to drain it, since that loop is gated behind the
  registration wait that never resolves. Confirmed this was real, not
  theoretical, with a live `TestClient` script before writing any fix:
  opened one connection and sent it nothing, posted three unrelated matched
  pairs, and that idle connection's own queue (reached directly off
  `engine._subscribers`) had all three sitting in it, `qsize() == 3`, with
  the connection itself still present in `engine._subscribers` -- a
  real, unbounded-over-time memory leak (one queue per never-registered
  connection, growing by one entry per match made anywhere on the server,
  for as long as the process runs) and a dangling server-side task/socket
  that nothing ever closes, from an endpoint anyone can reach with zero
  authentication.
- Fix: a new named `REGISTRATION_TIMEOUT_SECONDS` constant (10.0) and
  `asyncio.wait_for()` around the registration `receive_json()` call. A real
  client (`app/static/live.js` sends its id the instant the socket opens)
  clears this in milliseconds and never notices it; a connection that never
  registers now gets closed (code `1008`, the same code the existing
  malformed-registration path already used) once the timeout fires instead
  of being left open indefinitely -- `asyncio.TimeoutError` falls through
  the same `except Exception:` branch that already handled a malformed
  registration, so no new branch was needed, just the timeout itself.
- Tests: `tests/test_live_matches.py` adds
  `test_a_connection_that_never_registers_is_closed_after_a_timeout_not_left_hanging_forever`
  -- the exact reproduction above (connect, send nothing), asserting the
  connection gets a `WebSocketDisconnect` on its next receive *and* that it's
  actually gone from `engine._subscribers`, not just closed client-side.
  Shrinks `app.router.REGISTRATION_TIMEOUT_SECONDS` to `0.2` for the
  duration of the test (restored in a `finally`) so it doesn't have to wait
  out the real 10s default, same pattern as task 30's rate-limiter test
  shrinking `MIN_SECONDS_BETWEEN_REQUESTS`. Ran it against the pre-fix code
  first (temporarily stashing just `app/router.py`) to confirm it actually
  fails there -- it does, with an `AttributeError` since
  `REGISTRATION_TIMEOUT_SECONDS` doesn't exist pre-fix at all, confirming
  the test can't pass by accident -- not just that it passes now. Full
  suite: 178 tests, up from 177, all green.

### 41. Stop /matches from broadcasting every match's request ids to every connection, not just the two people in it
- Not a numbered "Up next" item -- "Up next" only has tasks 13/19 on it and
  both are manual-only, so this evening run went looking for a real bug the
  same way the last several runs did, and found a real privacy hole in
  `app/router.py`'s `stream_matches()` -- the WS endpoint itself, not a
  validation gap next to it the way most of the last dozen entries here
  were.
- `GET /requests/{id}?viewer_request_id=` (TASKS.md #7) treats knowing a
  request's own id as the *only* proof needed to view that request's
  precise origin/destination/contact once it's matched -- its own
  docstring says the id is "unguessable... and never displayed to anyone
  else -- doubling as proof." But `stream_matches()` had no registration
  step at all: it `await websocket.accept()`ed, subscribed, and forwarded
  *every* `MatchGroup` straight to *every* connected client, no auth
  required to connect (SCOPE.md: no SMS/OTP for the MVP, so there's
  nothing gating who can open this endpoint at all). That handed both
  halves of every match's ids to a completely uninvolved third party for
  free -- directly contradicting SCOPE.md's own "exact pickup point and
  contact info are exchanged only between two people after they mutually
  match -- never broadcast." Confirmed this was real, not theoretical,
  with a live `TestClient` script before writing any fix: a connection
  that never posted a request of its own, and never identified itself as
  anyone, opened `/matches`, received a real match's two request ids off
  that raw broadcast, and then called `GET
  /requests/{a_id}?viewer_request_id=<the other id from that event>` and
  got back a `200` with that stranger's full precise pickup/dropoff and
  real contact info -- a complete stranger's "proof of involvement,"
  handed over by the one channel that was supposed to make it
  unguessable.
- Fix: `stream_matches()` now requires the first message a connection sends
  after opening to be its own request id (`{"request_id": "<uuid>"}`); only
  a `MatchGroup` that actually names that id gets forwarded, everything
  else is drained from this connection's own queue and silently dropped.
  Subscribing to the engine (`queue = engine.subscribe()`) still happens
  *before* waiting for that id, not after -- a match involving this
  connection's own request can be produced essentially immediately
  (scored against whatever's already pooled, inside the same event-loop
  hop that processes a brand-new `POST`), so subscribing first means
  nothing racing that gap is lost; it just sits in this connection's own
  queue, in order, until the id arrives. A malformed/missing registration
  (bad JSON, no `request_id` field, not a real UUID) closes the socket
  (code `1008`) instead of hanging forever waiting for one that'll never
  parse. `app/static/live.js` sends its own id right after the socket
  opens -- by the time that page exists the rider's own id is already
  known, handed back by `POST /requests` -- and keeps its existing
  client-side id check too, as a harmless belt-and-suspenders second
  layer, not the only layer anymore. `app/matching/engine.py` itself is
  untouched: `subscribe()`/`unsubscribe()` still hand back a raw,
  unfiltered copy of every match to whoever asks, exactly as before --
  that's an internal, non-networked mechanism now gated by the one real
  entry point that exposes it over the network, not the thing that needed
  fixing.
- `simulate.py` used to open one global, unfiltered `/matches` connection
  to narrate every match in the demo run -- that's exactly the capability
  this fix removes, so it now opens one filtered connection *per posted
  request* instead (connected, and so already subscribed, *before* that
  request is posted, for the same race-safety reason as the router's own
  fix), with a shared `printed` set deduping a match that would otherwise
  arrive once from each side of the pair's own feed. Same "every match
  prints once, as it happens" demo behavior as before, just without
  resurrecting a global broadcast to get it.
- Tests: `tests/test_live_matches.py` adds
  `test_a_connection_never_receives_a_match_it_did_not_register_for` (the
  real reproduction above -- a connection that posts nothing, sits
  through an unrelated `a<->b` match while still unregistered, then
  registers for a *different* `c<->d` pair and asserts that `c<->d` is
  the only thing it ever receives, proving `a<->b` was dropped server-side
  rather than just not-yet-delivered) and
  `test_a_connection_with_a_malformed_registration_is_closed_not_left_hanging`.
  Updated every existing `/matches` test
  (`tests/test_requests_api.py`'s three, `tests/test_live_matches.py`'s
  two) to register with the right id before expecting a match --
  including the two-simultaneous-tabs test, now explicitly registering
  both tabs for the *same* rider's own request, which is the real
  two-tabs scenario (one rider, two devices) this was always meant to
  cover. Ran the new regression test against the pre-fix code first
  (temporarily stashing just `app/router.py`) to confirm it actually fails
  there -- the unregistered bystander received `a<->b` as its first
  message, not `c<->d` -- not just that it passes now. Full suite: 177
  tests, up from 175, all green.

### 40. Reject a seats_needed past Postgres' INTEGER range instead of 500ing inside the DB driver
- Not a numbered "Up next" item -- "Up next" only has tasks 13/19 on it and
  both are manual-only, so this morning run went looking for a real bug the
  same way the last several runs did, and found one right next to task 39's
  own NUL-byte fix: the same "a DB column has a real limit the schema never
  enforced" shape, just on `seats_needed` instead of `rider_id`/`contact`.
- `app/schemas.py`'s `RideRequestCreate.seats_needed`/`RideRequest.seats_needed`
  had `Field(ge=1)` -- a floor, but no ceiling -- while `app/models.py`'s
  `seats_needed` column is a plain Postgres `INTEGER` (4 bytes, signed range
  up to 2147483647). Confirmed this was real, not theoretical, with a live
  `TestClient` call before writing any fix: `POST /requests` with
  `seats_needed=99999999999999` validated cleanly through
  `RideRequestCreate`, then 500'd inside `RequestStore.add()`'s
  `session.commit()` with a bare `sqlalchemy.exc.DataError` wrapping
  `psycopg2.errors.NumericValueOutOfRange: integer out of range`, the exact
  same "validates fine, crashes three
  layers down inside the DB driver" shape as task 39's NUL byte and task
  37's timezone-aware datetime, just on an integer column overflowing
  instead of a text column rejecting a byte or a naive/aware datetime
  comparison blowing up.
- Fix: new `MAX_SEATS_NEEDED = 2_147_483_647` constant (named, not a magic
  number, same pattern as `scoring.py`'s weights) and `Field(ge=1,
  le=MAX_SEATS_NEEDED)` on both `RideRequestCreate.seats_needed` and
  `RideRequest.seats_needed`. Deliberately tied to the actual Postgres
  `INTEGER` column's own signed range, not to any opinion about how large a
  real ride-pool party should be -- that's a separate question the engine's
  own hard capacity constraint (`app/matching/scoring.py`'s
  `capacity_fits()`) already handles on its own terms, and this fix doesn't
  need to guess at it to stop the crash. Added the bound to `RideRequest`
  itself too, not just the `RideRequestCreate` intake boundary -- unlike
  `rider_id`/`contact` (`NonBlankStr`), there's no legitimate
  already-anonymized or otherwise-mutated stored row this would ever need
  to still load, since nothing in this codebase ever raises a request's own
  `seats_needed` after intake.
- Tests: `tests/test_schemas.py` adds
  `test_ride_request_create_rejects_seats_needed_beyond_postgres_integer_range`
  and `test_ride_request_itself_also_rejects_seats_needed_beyond_postgres_integer_range`
  (both models, the exact `99_999_999_999_999` reproduction above).
  `tests/test_requests_api.py` adds the HTTP-level reproduction,
  `test_create_request_rejects_seats_needed_beyond_postgres_integer_range`
  -- the exact `seats_needed=99999999999999` payload above now `422`s
  instead of `500`ing. Ran all three against the pre-fix code first
  (temporarily stashing just `app/schemas.py`) to confirm they actually
  fail there -- a real `500`/`DataError` for the HTTP test, a clean
  "did not raise" for the two model-level tests, not just that they pass
  now. Full suite: 175 tests, up from 172, all green.

### 39. Reject a NUL character in rider_id/contact/report-reason instead of 500ing inside the DB driver
- Not a numbered "Up next" item -- "Up next" only has tasks 13/19 on it and
  both are manual-only, so this evening run went looking for a real bug the
  same way the last several runs did, and found one right next to the
  whitespace-only gap task 27 already closed in the same three fields.
- A NUL byte (`"\u0000"`) is a perfectly ordinary character as far as a JSON
  string and Pydantic's `str` type are concerned -- it's neither empty nor
  whitespace, so neither `Field(min_length=1)` nor `_reject_blank` (task 27)
  catches it. But `rider_id`/`contact`/an abuse report's `reason` all end up
  in a Postgres text column (`app/store.py`'s `_to_orm()`, `app/reports.py`'s
  `_to_orm()`), and libpq refuses outright to send a string containing one.
  Confirmed this was real, not theoretical, with a live `TestClient` call
  before writing any fix: `POST /requests` with
  `rider_id="rider-\u0000null"` validated cleanly through
  `RideRequestCreate` and then raised a bare `ValueError: A string literal
  cannot contain NUL (0x00) characters` deep inside
  `RequestStore.add()`'s `session.commit()` -- a real `500`, not a `422`
  from intake, the exact same "validates fine, crashes three layers down"
  shape as task 37's timezone-aware-datetime bug, just hitting the DB
  driver instead of a bare datetime comparison. The same payload on
  `contact`, and the equivalent on `AbuseReportCreate.reason`
  (`POST /requests/{id}/report`), crashed the same way.
- Fix: new `_reject_nul()` validator, chained onto the same `NonBlankStr`
  `rider_id`/`contact`/`reason` already share (`Annotated[str,
  Field(min_length=1), AfterValidator(_reject_blank),
  AfterValidator(_reject_nul)]`) -- rejects any value containing `"\x00"`
  with a clean `ValueError` a 422 can represent, at the same intake
  boundary `_reject_blank` already guards, before it ever reaches a
  session.commit(). No change to `RideRequest`/`AbuseReport` (the
  internal/stored shapes), same reasoning as task 26/27: those also have to
  keep representing whatever's already stored, and nothing stored can ever
  contain a NUL byte now that intake rejects it.
- Tests: `tests/test_schemas.py` adds
  `test_ride_request_create_rejects_a_nul_character_in_rider_id_or_contact`
  (both fields, at the `RideRequestCreate` level). `tests/test_requests_api.py`
  adds the HTTP-level reproduction,
  `test_create_request_rejects_a_nul_character_in_rider_id_or_contact` --
  the exact `rider_id="rider-\x00null"` payload above now `422`s instead of
  `500`ing. `tests/test_reports.py` adds the same case for
  `AbuseReportCreate.reason`,
  `test_post_report_with_a_nul_character_in_reason_is_rejected`. Ran all
  four against the pre-fix code first (temporarily stashing just
  `app/schemas.py`) to confirm they actually fail there -- a real `500`
  with the exact psycopg2 `ValueError` above, not just that they pass now.
  Full suite: 172 tests, up from 168, all green.

### 38. Reject a `schedule` that mixes one-off and recurring fields instead of silently picking one
- Not a numbered "Up next" item -- "Up next" only has tasks 13/19 on it and
  both are manual-only, so this morning run went looking for a real bug the
  same way the last several runs did, and found one in how `app/schemas.py`'s
  `schedule: Union[OneOffSchedule, RecurringSchedule]` actually resolves an
  ambiguous input, not in either schedule model's own field checks.
- There's no discriminator field telling Pydantic which shape a `schedule`
  dict is meant to be -- it decides with its own "smart union" matching, and
  by default an unrecognized field is just dropped, not rejected. That means
  a dict carrying fields from *both* shapes at once -- plausible from a non-
  browser client that edited a request from one schedule type to the other
  and left the old fields in, not something the web form's radio-button UI
  can produce but nothing stops a raw API client from sending -- doesn't
  trip either model's own validation. Confirmed this was real, not
  theoretical, with a live script before writing any fix:
  `RideRequestCreate` built with a `schedule` dict holding
  `earliest_departure`/`latest_departure` *and* `weekdays`/
  `earliest_departure_time`/`latest_departure_time` together validated
  clean and came back as a `RecurringSchedule` -- the one-off date info just
  vanished, no error, and `POST /requests` with the same payload returned a
  real `201`, silently storing a *weekly Monday/Tuesday/Wednesday recurring
  request* instead of the one-off trip the dropped fields actually named.
  Nothing anywhere told the caller their request didn't mean what got
  stored.
- Fix: both `OneOffSchedule` and `RecurringSchedule` now set
  `model_config = ConfigDict(extra="forbid")`. A field that belongs to
  neither shape -- which is exactly what a field belonging to the *other*
  shape is, from either model's own point of view -- is now a clean `422`
  instead of silently tolerated. Checked every existing caller that builds
  one of these from a plain dict (`app/web.py`'s form handler, `app/store.py`'s
  `_row_to_schedule`, `app/matching/scoring.py`'s `expand_schedule`,
  `app/privacy.py`'s `fuzz_schedule`) and every schedule dict in the test
  suite -- all of them already pass only the fields that belong to the
  shape they're building, so none of them trip the new constraint; this
  only closes the gap for a payload that mixes the two on purpose or by
  mistake.
- Tests: `tests/test_schemas.py` adds
  `test_ride_request_create_rejects_a_schedule_mixing_one_off_and_recurring_fields`
  (the exact reproduction above, at the `RideRequestCreate` level) and
  `test_one_off_schedule_rejects_stray_recurring_fields`/
  `test_recurring_schedule_rejects_stray_one_off_fields` (each schedule
  model directly, one stray field from the other shape). `tests/test_requests_api.py`
  adds the HTTP-level reproduction,
  `test_create_request_rejects_a_schedule_mixing_one_off_and_recurring_fields`
  -- the exact mixed-schedule `POST /requests` payload above now `422`s
  instead of `201`ing as a recurring request. Ran all four against the
  pre-fix code first (temporarily stashing just `app/schemas.py`) to confirm
  they actually fail there -- a real `201`/silent `RecurringSchedule`, not
  just that they pass now. Full suite: 168 tests, up from 164, all green.

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

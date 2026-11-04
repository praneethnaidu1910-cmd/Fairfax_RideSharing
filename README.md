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

Requests are stored in Postgres (TASKS.md #9), so a running Postgres
instance and a `DATABASE_URL` are required — nothing falls back to
in-memory or SQLite.

```bash
# once: create a database and point DATABASE_URL at it
createdb fairfax_ridesharing
export DATABASE_URL="postgresql+psycopg2://<user>:<password>@127.0.0.1:5432/fairfax_ridesharing"

cd backend
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```

```bash
cd backend
pytest
```

The test suite doesn't reuse `DATABASE_URL` above — it defaults (see
`tests/conftest.py`) to a separate local `fairfax_ridesharing_test`
database so test runs never touch dev data, applying the real Alembic
migrations at the start of the run and truncating `ride_requests` between
tests. Override with `DATABASE_URL` if your local Postgres role/database
names differ from the default `fairfax_app`/`fairfax_ridesharing_test`.

## Geocoding: place names to coordinates

`GET /geocode?q=<place name>` (TASKS.md #10) wraps Nominatim (OpenStreetMap)
to turn something like "GMU" or "Fairfax Corner" into a `{lat, lng}` — this
is what a client calls *before* `POST /requests`, not a change to that
endpoint's shape. It 404s with a clear error for an unrecognized place
rather than guessing.

`pytest` only exercises this with the real Nominatim call mocked — this
sandbox's own outbound network policy denies `nominatim.openstreetmap.org`
outright, so automated runs can prove the request-shaping and
error-handling logic but not that the live API actually resolves a real
place. That live check is manual, from a machine with normal network
access:

```bash
curl "http://127.0.0.1:8000/geocode?q=George+Mason+University"
# {"lat": 38.83..., "lng": -77.30...} -- plausible Fairfax-area coordinates
curl "http://127.0.0.1:8000/geocode?q=Definitely+Not+A+Real+Place+XYZ"
# 404, clear error, not a silent wrong match
```

## Simulator: watch the sample dataset match in real time

With the server running (`uvicorn app.main:app --reload` from `backend/`),
replay the full sample dataset against it with staggered, compressed timing
and watch match events print as they're found, not just at the end:

```bash
python backend/simulate.py
```

## Manual smoke test: structured intake + live matches

The simulator above is the automated version of this; the walkthrough below
is the same thing done by hand, one request at a time, if you want to see
each step. With the server running (`uvicorn app.main:app --reload` from
`backend/`), open a WebSocket subscriber first so you can watch a match
arrive, then post two compatible requests from another terminal.

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

## Web frontend: submit, browse, and watch for a live match

With the server running (`uvicorn app.main:app --reload` from `backend/`),
`GET /new` (TASKS.md #11) is the structured intake form -- type a place name
in the pickup/destination fields and it geocodes to lat/lng in the
background (TASKS.md #10) before the form posts. Submitting redirects to
`GET /mine/<request-id>` (TASKS.md #12), which opens a WebSocket to
`/matches` and reveals the counterpart's real pickup point and contact the
moment a match is found -- no page reload. `GET /browse` lists every open
request in the same coarse, privacy-safe shape `GET /requests` returns.

Manual smoke test, the UI equivalent of the WebSocket/curl one above --
this is what TASKS.md #12's acceptance criterion asks for, since there's no
browser in this project's automated test sandbox to drive two tabs at once:

1. Open `http://127.0.0.1:8000/new` in **two separate browser tabs**.
2. In tab 1, post a one-off request (e.g. Fairfax -> Aldie, a departure
   window a couple hours out). You land on `/mine/<id>`, showing "Waiting
   for a match..."
3. In tab 2, post a compatible request (close-but-not-identical origin,
   same destination, an overlapping window -- mirroring the root README's
   curl example above).
4. Both tabs should update **within a second or two, without reloading**:
   tab 1 shows tab 2's rider/contact/pickup/dropoff, and vice versa.

Verified this exact flow with a headless-Chromium (Playwright) script
against a live server in this sandbox, since `/geocode`'s own real-network
call is blocked here the same way TASKS.md #10 already documents -- the
script stubs that one endpoint and drives the rest of the app for real: two
tabs, two posted requests, both reveals appearing live. That run also
caught a real bug fixed alongside this: `app/static/app.js` was treating
any failed `/geocode` call (including a transient 500) the same as a
confirmed 404 "place not found," silently wiping out a field the rider had
already filled in correctly.

## Data retention

SCOPE.md flags "real data protection for real location data" as a real
requirement, not just an engineering nice-to-have -- so a matched,
cancelled, or expired request's precise pickup/dropoff and contact info
don't just sit in Postgres forever. `app/retention.py` defines the policy
(`RETENTION_DAYS = 30`, counted from whichever of these happened:
matched, cancelled, or -- for a one-off request only, see
docs/MATCHING_ALGORITHM.md's "Request lifecycle" section -- its window
expiring), and `RequestStore.anonymize_stale()` (`app/store.py`) is what
actually overwrites the stale row: the exact origin/destination point
becomes its own neighborhood-level H3 cell center (the same granularity
every other user already sees pre-match) and `contact` becomes an empty
string. Already-anonymized rows are skipped on every later run.

This doesn't run on its own -- there's no in-app scheduler (same posture
as TASKS.md #14's expiry, except this one has to mutate stored rows, so
it needs a real external trigger). Run it periodically once the app is
deployed, e.g. a daily cron entry:

```bash
cd backend && python scripts/anonymize_stale_requests.py
```

## Deploying

TASKS.md #13 (getting this onto a real public URL) needs a hosting account
and billing, which is a by-hand step, not something an automated run does.
This section is the rest of it -- the part that doesn't touch an account or
spend money, so task 13 itself is just "sign up for hosting and point it at
this."

**Health check.** `GET /healthz` actually exercises the database connection
(`SELECT 1`), not just "is the process running" -- it returns `200
{"status": "ok"}` when Postgres is reachable and `503
{"status": "error", ...}` when it isn't, which is what a hosting platform's
health check/readiness probe should poll.

**Container image.** `backend/Dockerfile` builds the app and runs
`alembic upgrade head` on every container start (a no-op once the schema's
already current) before starting `uvicorn` bound to `0.0.0.0:8000` -- no
`--reload`, since that's a local-dev convenience, not something a
production container needs. `DATABASE_URL` is never baked into the image;
pass it (and `ALLOWED_ORIGINS` below, if needed) as a container env var at
deploy time, same as running locally:

```bash
cd backend
docker build -t fairfax-ridesharing .
docker run -p 8000:8000 \
  -e DATABASE_URL="postgresql+psycopg2://<user>:<password>@<host>:5432/<db>" \
  fairfax-ridesharing
```

Not yet verified by actually building the image -- this sandbox's Docker
daemon can't be started here (no permission to run one inside this
container), the same kind of real environment limitation TASKS.md #10's
geocoding and #12's browser checks already ran into. Worth a real `docker
build`/`docker run` by hand once there's a machine with a working Docker
daemon, before trusting this is the final word on the image.

**CORS.** FastAPI adds no CORS headers unless told to -- browsers block
every cross-origin request by default, which is fine until the frontend is
served from a different origin than the API (e.g. a static site calling a
separately-hosted API). `ALLOWED_ORIGINS` is a comma-separated env var
naming exactly which origin(s) may call this API cross-origin; unset (the
default, same as running locally) means no CORS middleware is added at all
-- restrictive by default, never a wildcard:

```bash
export ALLOWED_ORIGINS="https://your-frontend-domain.example"
```

**Debug.** FastAPI's own `debug` flag already defaults to `False` and
nothing in `app/main.py` turns it on, so there's no production/dev config
split to get wrong here -- noting it since task 18 asked for this to be a
documented, deliberate choice rather than an unexamined default.

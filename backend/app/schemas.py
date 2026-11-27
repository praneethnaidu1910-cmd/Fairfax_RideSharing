import unicodedata
from datetime import datetime, time
from enum import Enum
from typing import Annotated, Optional, Union
from uuid import UUID, uuid4

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from app.geo import h3_cell


def _reject_blank(value: str) -> str:
    """Field(min_length=1) alone lets a whitespace-only string ("   ")
    through -- its length is >= 1, even though it's exactly as useless as
    the empty string that validator is meant to catch. Used below for
    every field whose whole point is reaching a real person (rider_id,
    contact, an abuse report's reason): a blank-but-not-technically-empty
    value would sail through intake the same way plain "" used to before
    the Field(min_length=1) fix, defeating the same purpose that fix
    closed. Doesn't strip the value -- a legitimately non-blank string
    with incidental leading/trailing whitespace (" John ") is left as the
    rider typed it, not normalized.

    `str.strip()` only recognizes whitespace -- it leaves a Unicode
    "format" character (category Cf: zero-width space U+200B, zero-width
    joiner/non-joiner, the BOM/zero-width-no-break-space U+FEFF, the
    left-to-right/right-to-left marks, ...) completely alone, since none
    of those are whitespace as far as Python's str is concerned. Every one
    of them is specifically designed to render as nothing, though, so a
    rider_id/contact/report-reason made up of nothing but them is exactly
    as blank to anyone who ever looks at it -- the matched counterpart's
    reveal, the abuse-report log -- as the empty or whitespace-only string
    this function already rejects, just invisible instead of using actual
    spaces. Confirmed this was real, not theoretical, with a live
    TestClient call before this fix: POST /requests with
    rider_id="\\u200b\\u200b\\u200b" (three zero-width spaces) and
    contact="\\ufeff\\u200c" validated cleanly and returned a real 201 --
    `value.strip()` doesn't remove either character, so neither looked
    blank to this check, even though both display as nothing."""
    if all(character.isspace() or unicodedata.category(character) == "Cf" for character in value):
        raise ValueError("must not be empty, whitespace-only, or made up of invisible characters")
    return value


def _reject_nul(value: str) -> str:
    """A NUL byte ("\\u0000") is a perfectly ordinary character as far as a
    JSON string and Pydantic's str type are concerned -- nothing about
    Field(min_length=1)/_reject_blank above rejects it, since it's neither
    empty nor whitespace. But every field this guards (rider_id, contact,
    an abuse report's reason) ends up as a Postgres text column
    (app/store.py's _to_orm(), app/reports.py's _to_orm()), and libpq
    refuses outright to send a string containing one: not a clean
    ValueError Pydantic could have turned into a 422, but a bare
    `ValueError: A string literal cannot contain NUL (0x00) characters`
    raised deep inside psycopg2/SQLAlchemy at commit time, well past any
    validation. Confirmed this was real, not theoretical, with a live
    TestClient call before writing this fix: POST /requests with
    rider_id="rider-\\u0000null" (valid JSON, Pydantic validated it
    cleanly) 500'd inside RequestStore.add()'s session.commit(), not a
    422 from intake. Rejecting it here, at the same intake boundary
    _reject_blank already guards, turns that into a clean 422 instead of
    an unhandled crash reaching all the way into the DB driver."""
    if "\x00" in value:
        raise ValueError("must not contain a NUL character")
    return value


# No ceiling on how long rider_id/contact/an abuse report's reason can be
# -- Field(min_length=1) above puts a floor on these fields but never a
# top, and nothing else in the stack catches it either: app/models.py's
# backing columns are a plain SQLAlchemy String (no length), which
# Postgres happily stores as an unbounded VARCHAR. Confirmed this was
# real, not theoretical, with a live TestClient call before this fix: POST
# /requests with a 50,000-character rider_id and contact validated cleanly
# and came back a real 201, and the GET /requests response right after
# -- the open list every anonymous caller polls, no auth required
# (SCOPE.md: open-join, no SMS/OTP) -- was itself 5MB+, just from that one
# row. A single, ordinary-looking POST permanently bloats every future
# caller's response to the public list for as long as that request stays
# open (indefinitely for a recurring one -- docs/MATCHING_ALGORITHM.md's
# "Request lifecycle" section), the same "one reachable POST degrades
# everyone else" shape as the duplicate-weekday and datetime-range fixes
# already in TASKS.md's own log, just on string length instead of list
# length or a datetime bound.
#
# SCOPE.md never states a number for this, the same situation
# app/retention.py's RETENTION_DAYS is already in -- so this is my own
# reasonable default (room for a real name, a phone number or WhatsApp
# handle, or a genuinely detailed abuse-report paragraph, several times
# over), not a hard system limit the way MAX_SEATS_NEEDED above is. Worth
# revisiting if a real policy is ever set.
MAX_TEXT_FIELD_LENGTH = 500

# A string that must have real, non-whitespace content, must not carry a
# NUL byte Postgres can't store, and must not run past
# MAX_TEXT_FIELD_LENGTH -- not just a non-empty one. See _reject_blank's
# and _reject_nul's own docstrings for why Field(min_length=1) alone isn't
# enough here, and MAX_TEXT_FIELD_LENGTH's own comment just above for why
# a ceiling is needed too.
NonBlankStr = Annotated[
    str,
    Field(min_length=1, max_length=MAX_TEXT_FIELD_LENGTH),
    AfterValidator(_reject_blank),
    AfterValidator(_reject_nul),
]

# app/models.py's seats_needed column is a plain Postgres INTEGER (4
# bytes) -- a signed value past this range can't be stored at all, the
# same "the DB column has a real limit the schema never enforced" shape
# as the NUL-byte fix above, just on seats_needed instead of
# rider_id/contact. Field(ge=1) alone put a floor on this field but never
# a ceiling, so a value past this range used to validate cleanly through
# RideRequestCreate/RideRequest and then crash deep inside the DB driver
# at session.commit() instead of 422ing at intake. Confirmed this was
# real, not theoretical, with a live TestClient call before this fix:
# POST /requests with seats_needed=99999999999999 validated cleanly here
# and then raised a bare `psycopg2.errors.NumericValueOutOfRange: integer
# out of range` inside RequestStore.add()'s session.commit(), a real 500,
# not a 422 from intake. This is the actual INTEGER column's own limit,
# not a stance on how many people a real ride pool should fit -- that's
# already a separate, hard capacity constraint the matching engine checks
# on its own (app/matching/scoring.py's capacity_fits()), not something
# this bound needs to guess at.
MAX_SEATS_NEEDED = 2_147_483_647


class Location(BaseModel):
    # Real-world latitude/longitude bounds -- without these a client typo
    # (or a bad Nominatim parse) like lat=999 was silently accepted and fed
    # straight into app/geo.py's haversine/bearing math (no error, since
    # math.sin/cos don't care that 999 degrees isn't a real latitude), so
    # matching quietly scored nonsense distances/bearings for an impossible
    # point instead of rejecting it at intake. SCOPE.md/docs/
    # MATCHING_ALGORITHM.md both assume real coordinates throughout; this
    # just makes that assumption an enforced one.
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)

    def coarse_cell(self) -> str:
        """Neighborhood-level H3 cell -- what other users see pre-match."""
        return h3_cell(self.lat, self.lng)


class OneOffSchedule(BaseModel):
    # `schedule` is `Union[OneOffSchedule, RecurringSchedule]` with no
    # discriminator field, so Pydantic's own "smart union" matching is what
    # decides which member a given dict becomes -- and by default an unknown
    # field is just dropped, not rejected. A payload carrying fields from
    # *both* shapes at once (e.g. a non-browser client with leftover
    # recurring fields still in a dict meant to be one-off, after editing
    # one schedule type into another) doesn't get caught by either model's
    # own field validation -- it silently matches whichever shape happens to
    # come first and the other shape's fields just vanish, no 422, no
    # indication the request didn't mean what was actually stored. Confirmed
    # real, not theoretical: POST /requests with both
    # earliest_departure/latest_departure AND weekdays/earliest_departure_time/
    # latest_departure_time in the same `schedule` dict returned 201 and
    # silently became a *recurring* Monday/Tuesday/Wednesday request --
    # dropping the one-off date entirely with no error, even though nothing
    # about that input said "recurring" on its own terms. extra="forbid"
    # makes a field that doesn't belong to either shape a clean 422 instead
    # of either model quietly accepting a subset of the payload.
    model_config = ConfigDict(extra="forbid")

    earliest_departure: datetime
    latest_departure: datetime

    @model_validator(mode="after")
    def _check_window(self) -> "OneOffSchedule":
        # Pydantic happily parses a timezone-aware ISO 8601 string (e.g. a
        # "Z" suffix, or "-05:00") into an aware datetime here -- but every
        # other datetime in this codebase (datetime.utcnow() in
        # scoring.is_expired()/RideRequest.posted_at/status_changed_at, the
        # DateTime(timezone=False) columns in app/models.py) is naive.
        # Comparing a naive and an aware datetime doesn't raise a clean
        # ValueError Pydantic can turn into a 422 -- it's a bare TypeError,
        # so it crashes straight through model validation (here, comparing
        # the two fields against each other) and, for a request that
        # passes this check, straight through is_expired() the first time
        # anything reads the request back. Confirmed real, not
        # theoretical: POST /requests with
        # earliest_departure="2026-01-01T14:00:00-05:00" -- a perfectly
        # normal thing for a non-browser API client to send -- 500s
        # instead of posting or 422ing. Rejecting it here, before the
        # comparison that would otherwise crash, turns that into a clean
        # 422 at the one place client input enters this shape.
        if self.earliest_departure.tzinfo is not None or self.latest_departure.tzinfo is not None:
            raise ValueError(
                "earliest_departure/latest_departure must not include timezone info"
            )
        if self.latest_departure < self.earliest_departure:
            raise ValueError("latest_departure must not be before earliest_departure")
        return self


class RecurringSchedule(BaseModel):
    # Same reasoning as OneOffSchedule.model_config just above -- without
    # this, a mixed one-off+recurring payload could just as easily match
    # *this* shape first instead, silently dropping earliest_departure/
    # latest_departure instead of weekdays/the time fields.
    model_config = ConfigDict(extra="forbid")

    # Monday=0 .. Sunday=6, matching datetime.date.weekday()
    weekdays: list[int]
    earliest_departure_time: time
    latest_departure_time: time

    @model_validator(mode="after")
    def _check_weekdays_and_window(self) -> "RecurringSchedule":
        if not self.weekdays:
            raise ValueError("recurring schedule needs at least one weekday")
        if any(day < 0 or day > 6 for day in self.weekdays):
            raise ValueError("weekdays must be 0 (Monday) through 6 (Sunday)")
        # `weekdays` means "which days of the week," a set of at most 7
        # distinct values (0-6) -- nothing above rejected a *repeated* one,
        # so a payload could carry an arbitrarily long list of duplicates
        # (e.g. weekdays=[0]*20000) and validate cleanly, since every
        # individual value is still in range. That's not just a wasted
        # payload: app/matching/scoring.py's expand_schedule() materializes
        # one OneOffSchedule instance per entry in this list (duplicates
        # included), and both match_batch() and on_new_request() then score
        # every one of those windows against every window on the other side
        # of a candidate pair -- so the cost of scoring this request against
        # anything else scales linearly with how many duplicates it was
        # posted with, not with how many distinct days it actually
        # represents. And because a RecurringSchedule never expires
        # (scoring.is_expired() always returns False for one) and
        # can_ever_be_matched() only looks at seat count, a small-enough
        # seats_needed keeps a request like this sitting in the live
        # matching pool -- repeatedly re-scored against every future
        # candidate that happens to bucket near it -- for as long as the
        # process runs. Confirmed this was real, not theoretical, with a
        # live script before this fix: pooling one such request
        # (weekdays=[0]*20000) and then submitting one ordinary, otherwise-
        # compatible request next to it made that single on_new_request()
        # call take ~180ms, versus a sub-millisecond ordinary match --
        # reachable through a single, ordinary-looking POST /requests call,
        # no auth required (SCOPE.md: open-join, no SMS/OTP). Rejecting a
        # repeated weekday here closes it at the source: a valid `weekdays`
        # can now never exceed 7 entries, since there are only 7 distinct
        # values 0-6 to begin with.
        if len(self.weekdays) != len(set(self.weekdays)):
            raise ValueError("weekdays must not contain duplicates")
        # Same gap as OneOffSchedule._check_window above, just on a bare
        # `time` instead of a `datetime` -- "09:00:00-05:00" parses to a
        # tz-aware time, and comparing it against a naive one below is the
        # same uncaught TypeError (confirmed live: a recurring schedule
        # with one tz-aware and one naive departure time 500s here, not a
        # 422), not a clean validation error.
        if (
            self.earliest_departure_time.tzinfo is not None
            or self.latest_departure_time.tzinfo is not None
        ):
            raise ValueError(
                "earliest_departure_time/latest_departure_time must not include timezone info"
            )
        if self.latest_departure_time < self.earliest_departure_time:
            raise ValueError(
                "latest_departure_time must not be before earliest_departure_time"
            )
        return self


class RequestStatus(str, Enum):
    OPEN = "open"
    MATCHED = "matched"
    EXPIRED = "expired"
    # Poster-initiated withdrawal (TASKS.md #15) -- distinct from EXPIRED,
    # which is time-based and computed, never stored. CANCELLED is written
    # once, directly, by POST /requests/{id}/cancel.
    CANCELLED = "cancelled"


class RideRequest(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    # Validated non-empty at intake, on RideRequestCreate below -- not
    # re-validated here, because this is also the shape app/store.py's
    # _from_orm() reconstructs straight from a stored row, including an
    # already-anonymized one (TASKS.md #17's anonymize_stale() deliberately
    # overwrites `contact` with "" as part of scrubbing a stale row's real
    # data) -- a min_length constraint here would make that already-stored,
    # intentionally-blanked state fail to load at all.
    rider_id: str
    origin: Location
    destination: Location
    # One-off window or a recurring weekday pattern -- never both.
    schedule: Union[OneOffSchedule, RecurringSchedule]
    seats_needed: int = Field(default=1, ge=1, le=MAX_SEATS_NEEDED)
    # Collected at request time so a match can reach the other party; must
    # not appear in any pre-match serialized response (TASKS.md #6).
    contact: str
    status: RequestStatus = RequestStatus.OPEN
    posted_at: datetime = Field(default_factory=datetime.utcnow)
    # Set by the matching engine at match time (never by a client). The one
    # other request this one is allowed to reveal precise location/contact
    # to (TASKS.md #7) -- None until matched.
    matched_with: Optional[UUID] = None
    # When `status` last moved away from OPEN (set by MatchingEngine on a
    # match, by POST /requests/{id}/cancel on a cancel). None for a request
    # that's still open -- app/retention.py's terminal_at() is what turns
    # this (plus EXPIRED's own computed timestamp) into "when did this
    # become retention-eligible" (TASKS.md #17).
    status_changed_at: Optional[datetime] = None
    # Set once app/store.py's RequestStore.anonymize_stale() has overwritten
    # this request's precise location/contact (TASKS.md #17) -- None means
    # "not anonymized yet," and a request already anonymized is skipped on
    # every later run rather than re-processed.
    anonymized_at: Optional[datetime] = None


class MatchGroup(BaseModel):
    request_ids: list[UUID]
    score: float
    reason: str


class RideRequestCreate(BaseModel):
    """POST /requests body -- the structured intake form's fields (SCOPE.md:
    a web form, not free text). Excludes id/status/posted_at, which
    RideRequest assigns itself, so a client can't hand a request in as
    already `matched`."""

    # NonBlankStr on both: an empty (or, see _reject_blank, whitespace-only)
    # rider_id or contact used to be accepted here and would reach a match
    # untouched -- the matched counterpart's reveal (app/web.py's
    # mine.html / app/static/live.js) would then show "Matched! Your ride
    # partner, :" and a blank Contact line, silently defeating SCOPE.md's
    # whole stated reason for collecting `contact` ("so a matched pair can
    # reach each other"). Enforced here, at intake, rather than on
    # RideRequest itself, since that shape also has to represent an
    # already-anonymized stored row (TASKS.md #17), which blanks `contact`
    # to "" on purpose.
    rider_id: NonBlankStr
    origin: Location
    destination: Location
    schedule: Union[OneOffSchedule, RecurringSchedule]
    seats_needed: int = Field(default=1, ge=1, le=MAX_SEATS_NEEDED)
    contact: NonBlankStr


class AbuseReportCreate(BaseModel):
    """POST /requests/{id}/report body (TASKS.md #16) -- a rider flagging a
    problem with a specific request/counterpart. `reporter_request_id` is
    optional: the same no-login "proof of involvement" as
    `viewer_request_id` elsewhere, but someone just browsing the public
    list without ever posting a request of their own can still report
    something they saw."""

    # NonBlankStr, not just Field(min_length=1) -- see _reject_blank's
    # docstring: a whitespace-only reason ("   ") would otherwise be
    # "stored" in name only, no more useful than the empty string this
    # field is already supposed to reject.
    reason: NonBlankStr
    reporter_request_id: Optional[UUID] = None


class AbuseReport(BaseModel):
    """Stored shape (app/reports.py) -- never serialized into any response;
    this table backs no public read path at all (TASKS.md #16: "visible
    nowhere publicly")."""

    id: UUID = Field(default_factory=uuid4)
    reported_request_id: UUID
    reporter_request_id: Optional[UUID] = None
    reason: str = Field(min_length=1)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class RideRequestPublic(BaseModel):
    """Coarse location + fuzzed time only, never the precise Location or
    `contact` (SCOPE.md: "no exact address, ever, pre-match"). Built by
    app/privacy.py's to_public(), not a method here, so this module
    doesn't need app.geo's fuzzing helpers.

    Includes `id` -- safe only because every caller that gets this shape
    already supplied that id themselves: `POST /requests`'s own response
    (handing a brand-new id to its rightful owner for the first time),
    `POST /requests/{id}/cancel`'s response, and `GET /requests/{id}`
    (the id was already in the URL). See RideRequestListItem just below
    for the shape that's actually safe to hand to someone who *doesn't*
    already know the id.
    """

    id: UUID
    rider_id: str
    origin_area: str
    destination_area: str
    schedule: Union[OneOffSchedule, RecurringSchedule]
    seats_needed: int
    status: RequestStatus
    posted_at: datetime


class RideRequestListItem(BaseModel):
    """GET /requests and GET /browse's shape -- the open-requests list an
    anonymous browser scrolls, same trust level as the WhatsApp group
    today. Identical coarse/fuzzed fields to RideRequestPublic, with one
    deliberate omission: no `id`.

    `GET /requests/{id}?viewer_request_id=` (TASKS.md #7) treats knowing a
    request's own id as the *only* proof needed to see that request's
    precise origin/destination/contact once it's matched -- its own
    docstring calls the id "unguessable... and never displayed to anyone
    else." That was never actually true while `RideRequestPublic` (id
    included) was also what the open list returned: every id was sitting
    in plain sight in `GET /requests`' response body before a match even
    happened, to literally anyone, no auth required (SCOPE.md: open-join,
    no SMS/OTP). An uninvolved caller could scrape that list, wait for two
    previously-listed ids to drop off it (a cheap, public signal that
    those two just matched each other), and then call `GET
    /requests/{a}?viewer_request_id={b}` using nothing but those two
    publicly-scraped ids -- getting back a's full precise pickup/dropoff
    and real contact info, exactly the thing SCOPE.md says gets
    "exchanged only between two people after they mutually match -- never
    broadcast," with no guessing needed at all. Confirmed real, not
    theoretical, with a live script before writing this fix: posted two
    compatible riders, recorded both ids straight off a real `GET
    /requests` call made *before* they matched, confirmed both ids
    vanished from that same list once they did, and then used that
    scraped pair to pull a full reveal through `GET /requests/{id}
    ?viewer_request_id=` as an otherwise completely uninvolved caller --
    no websocket, no guessing, nothing but two already-public GET calls.
    No caller of the open list legitimately needs the id back: the
    poster already gets their own id for real from `POST /requests`'s own
    response (never from this list), and the matched counterpart learns
    the other id from the `/matches` WebSocket event itself (already
    filtered to the two involved parties, not this list either) -- so
    dropping `id` here closes the hole without taking anything away from
    a real caller.
    """

    rider_id: str
    origin_area: str
    destination_area: str
    schedule: Union[OneOffSchedule, RecurringSchedule]
    seats_needed: int
    status: RequestStatus
    posted_at: datetime

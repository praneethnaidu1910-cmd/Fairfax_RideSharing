from datetime import datetime, time
from enum import Enum
from typing import Optional, Union
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator

from app.geo import h3_cell


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
    earliest_departure: datetime
    latest_departure: datetime

    @model_validator(mode="after")
    def _check_window(self) -> "OneOffSchedule":
        if self.latest_departure < self.earliest_departure:
            raise ValueError("latest_departure must not be before earliest_departure")
        return self


class RecurringSchedule(BaseModel):
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
    seats_needed: int = Field(default=1, ge=1)
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

    # min_length=1 on both: an empty rider_id or contact used to be
    # accepted here and would reach a match untouched -- the matched
    # counterpart's reveal (app/web.py's mine.html / app/static/live.js)
    # would then show "Matched! Your ride partner, :" and an empty Contact
    # line, silently defeating SCOPE.md's whole stated reason for
    # collecting `contact` ("so a matched pair can reach each other").
    # Enforced here, at intake, rather than on RideRequest itself, since
    # that shape also has to represent an already-anonymized stored row
    # (TASKS.md #17), which blanks `contact` to "" on purpose.
    rider_id: str = Field(min_length=1)
    origin: Location
    destination: Location
    schedule: Union[OneOffSchedule, RecurringSchedule]
    seats_needed: int = Field(default=1, ge=1)
    contact: str = Field(min_length=1)


class AbuseReportCreate(BaseModel):
    """POST /requests/{id}/report body (TASKS.md #16) -- a rider flagging a
    problem with a specific request/counterpart. `reporter_request_id` is
    optional: the same no-login "proof of involvement" as
    `viewer_request_id` elsewhere, but someone just browsing the public
    list without ever posting a request of their own can still report
    something they saw."""

    reason: str = Field(min_length=1)
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
    """GET /requests shape -- coarse location + fuzzed time only, never the
    precise Location or `contact` (SCOPE.md: "no exact address, ever,
    pre-match"). Built by app/privacy.py's to_public(), not a method here,
    so this module doesn't need app.geo's fuzzing helpers."""

    id: UUID
    rider_id: str
    origin_area: str
    destination_area: str
    schedule: Union[OneOffSchedule, RecurringSchedule]
    seats_needed: int
    status: RequestStatus
    posted_at: datetime

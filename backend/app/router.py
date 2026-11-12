"""Structured intake + privacy-safe read API (TASKS.md #6).

engine and store live on app.state (set up in app/main.py's lifespan), not
as module-level singletons here -- that way each `with TestClient(app) as
client:` block in tests gets a fresh engine/store instead of leaking
matched state between tests.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect

from app.geocoding import PlaceNotFoundError, geocode_place
from app.privacy import to_public
from app.schemas import (
    AbuseReport,
    AbuseReportCreate,
    Location,
    RequestStatus,
    RideRequest,
    RideRequestCreate,
    RideRequestPublic,
)

router = APIRouter()


@router.get("/geocode", response_model=Location)
def geocode(q: str) -> Location:
    """Turns a free-text place name into coordinates (TASKS.md #10) -- the
    thing a client calls *before* POST /requests, not a change to that
    endpoint's shape. 404s with a clear message on no match rather than
    guessing a location."""
    try:
        return geocode_place(q)
    except PlaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/requests", response_model=RideRequestPublic, status_code=201)
async def create_request(payload: RideRequestCreate, request: Request) -> RideRequestPublic:
    ride_request = RideRequest(**payload.model_dump())
    request.app.state.store.add(ride_request)
    # Queues onto the engine's real-time pipeline (TASKS.md #5) rather than
    # matching inline -- run_forever() (started at app startup) picks it up
    # and publishes any match to engine.matches for /matches to stream.
    await request.app.state.engine.submit(ride_request)
    return to_public(ride_request)


@router.get("/requests", response_model=list[RideRequestPublic])
def list_requests(request: Request) -> list[RideRequestPublic]:
    return [to_public(r) for r in request.app.state.store.list_open()]


@router.get("/requests/{request_id}")
def get_request(request_id: UUID, request: Request, viewer_request_id: Optional[UUID] = None):
    """Coarse/redacted (same shape as GET /requests) for anyone, except the
    matched counterpart, who gets the precise Location + contact (TASKS.md
    #7, SCOPE.md: "exact pickup point and contact info are exchanged only
    between two people after they mutually match").

    There's no login/session system here (SCOPE.md: no SMS/OTP for the
    MVP), so `viewer_request_id` is the caller's own request id -- handed
    back to them by POST /requests, unguessable, and never displayed to
    anyone else -- doubling as their one proof of "I'm the other half of
    this match." Same open trust model SCOPE.md already accepts for
    contact exchange, just applied to who gets to ask.
    """
    store = request.app.state.store
    target = store.get(request_id)
    if target is None:
        raise HTTPException(status_code=404, detail="request not found")

    if target.matched_with is not None and viewer_request_id == target.matched_with:
        return target
    return to_public(target)


@router.post("/requests/{request_id}/cancel", response_model=RideRequestPublic)
def cancel_request(request_id: UUID, request: Request) -> RideRequestPublic:
    """Poster-initiated withdrawal (TASKS.md #15) -- SCOPE.md's "live
    status" item implies a way to stop being matched before a window
    passes or a match happens, and nothing provided that until now.

    Only an OPEN request can be cancelled: a MATCHED request already
    revealed contact info to its counterpart (there's no unmatch flow), an
    EXPIRED one is already unmatchable, and a second cancel on an
    already-CANCELLED one has nothing left to do. All three 409 rather
    than silently no-op, so a caller can tell a real cancel happened from
    one that didn't.

    Checks the same *computed* status to_public() reports (via
    to_public(target).status), not the raw stored value -- an EXPIRED
    one-off request's stored status never actually becomes "expired"
    (TASKS.md #14: that's a read-time computation, nothing ever writes it
    back), so comparing against the raw stored status let a caller cancel
    an already-expired request and get a 200 instead of the 409 this
    docstring has always described. That wasn't just a status-code mismatch:
    it flipped status_changed_at to "now," which is also what
    app/retention.py's terminal_at() reads to decide when a request became
    retention-eligible -- so "cancelling" an already-expired request reset
    its 30-day anonymization clock to start over from the cancel instead of
    from the window's own latest_departure, needlessly extending how long
    its precise location/contact sat around unredacted.
    """
    store = request.app.state.store
    target = store.get(request_id)
    if target is None:
        raise HTTPException(status_code=404, detail="request not found")
    effective_status = to_public(target).status
    if effective_status != RequestStatus.OPEN:
        raise HTTPException(
            status_code=409,
            detail=f"cannot cancel a request with status '{effective_status.value}'",
        )

    target.status = RequestStatus.CANCELLED
    # TASKS.md #17 reads this to know when a cancelled request became
    # retention-eligible -- same role as the matched_at stamp engine.py
    # writes on a match.
    target.status_changed_at = datetime.utcnow()
    store.save(target)
    # store.get() above returned a fresh instance, not whatever object
    # engine._unmatched may hold for this id -- this is what actually
    # stops it from winning a future match, not the status flip alone.
    request.app.state.engine.remove_from_pool(target.id)
    return to_public(target)


@router.post("/requests/{request_id}/report", status_code=201)
def report_request(request_id: UUID, payload: AbuseReportCreate, request: Request) -> dict[str, str]:
    """A rider flagging a problem with a specific request/counterpart
    (TASKS.md #16, SCOPE.md's "some way to handle harassment/abuse
    reports"). Durably stored, never surfaced in any public response --
    there's deliberately no GET for this, and no moderation workflow or
    admin UI to build yet; the minimal scope here is just making sure a
    report isn't lost.
    """
    store = request.app.state.store
    if store.get(request_id) is None:
        raise HTTPException(status_code=404, detail="request not found")

    report = AbuseReport(
        reported_request_id=request_id,
        reporter_request_id=payload.reporter_request_id,
        reason=payload.reason,
    )
    request.app.state.report_store.add(report)
    return {"status": "received"}


@router.websocket("/matches")
async def stream_matches(websocket: WebSocket) -> None:
    """Streams each MatchGroup as the engine finds it.

    Each connection gets its own queue from engine.subscribe() (TASKS.md
    #12) instead of reading engine.matches directly, so N simultaneous
    connections each receive a copy of every match rather than splitting
    them competing-consumer style -- the two-browser-tabs case #12's
    acceptance criterion needs actually works now.
    """
    await websocket.accept()
    engine = websocket.app.state.engine
    queue = engine.subscribe()
    try:
        while True:
            match = await queue.get()
            await websocket.send_json(match.model_dump(mode="json"))
    except WebSocketDisconnect:
        pass
    finally:
        engine.unsubscribe(queue)

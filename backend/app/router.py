"""Structured intake + privacy-safe read API (TASKS.md #6).

engine and store live on app.state (set up in app/main.py's lifespan), not
as module-level singletons here -- that way each `with TestClient(app) as
client:` block in tests gets a fresh engine/store instead of leaking
matched state between tests.
"""

import asyncio
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect

from app.geocoding import PlaceNotFoundError, geocode_place
from app.privacy import to_list_item, to_public
from app.schemas import (
    AbuseReport,
    AbuseReportCreate,
    Location,
    RequestStatus,
    RideRequest,
    RideRequestCreate,
    RideRequestListItem,
    RideRequestPublic,
)

router = APIRouter()

# How long stream_matches() below waits for a freshly-opened connection to
# send its registration message before giving up on it. app/static/live.js
# sends its id immediately once the socket opens, so a real browser client
# clears this in milliseconds -- this is only ever hit by a connection that
# never registers at all (a dropped client, a stalled script, or anyone
# just opening the endpoint and going quiet, which SCOPE.md's open-join/no-
# auth model lets anyone do with nothing more than a raw WebSocket client).
REGISTRATION_TIMEOUT_SECONDS = 10.0


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


@router.get("/requests", response_model=list[RideRequestListItem])
def list_requests(request: Request) -> list[RideRequestListItem]:
    """The open-requests list an anonymous browser scrolls -- deliberately
    never includes `id` (see RideRequestListItem's own docstring: this
    used to be a real, exploitable privacy hole, not a defense-in-depth
    nicety -- an uninvolved caller could scrape every open request's id
    straight off this endpoint, no auth required, then use two of them
    to pull a full post-match reveal through GET /requests/{id}
    ?viewer_request_id= once they vanished from this same list together).
    """
    return [to_list_item(r) for r in request.app.state.store.list_open()]


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

    Re-reads and re-checks the store a second time, right before writing
    the cancellation, instead of trusting the single read from the top of
    this function. This is a sync route, which Starlette dispatches to a
    threadpool worker, not the asyncio event loop that engine.run_forever()
    (and the on_new_request() it calls) runs on -- so a real match for
    this exact request can land in the gap between this function's first
    read and its write, the same kind of interleaving the engine's own
    on_new_request() already guards against from the opposite direction
    (app/matching/engine.py's two "store-backed race" rechecks). Without
    this second check, writing CANCELLED here would use `target` as read
    *before* that match -- silently overwriting a real match's MATCHED
    status and wiping its matched_with back to None, while the matched
    counterpart's own row still points back at this one, now-inconsistent
    id. Confirmed real, not theoretical, with a live script before this
    fix: captured cancel_request()'s own first read of an OPEN, pooled
    request, ran the real on_new_request() against it from a concurrent
    caller (matching it for real, flipping its stored status to MATCHED),
    then resumed the stale cancel with that first read -- the DB came back
    CANCELLED/matched_with=None, erasing the match, while the counterpart's
    row still said MATCHED/matched_with=<the erased request's id>.
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

    target = store.get(request_id)
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
    """Streams each MatchGroup involving *this connection's own* request --
    never every match that happens, no matter who's watching.

    Each connection gets its own queue from engine.subscribe() (TASKS.md
    #12) instead of reading engine.matches directly, so N simultaneous
    connections each receive a copy of every match rather than splitting
    them competing-consumer style -- the two-browser-tabs case #12's
    acceptance criterion needs.

    Used to forward every one of those copies straight to the client with
    no filtering at all -- which meant a completely uninvolved connection,
    one that never posted a request of its own, received both parties'
    request ids for *every* match anyone made, just by opening this
    endpoint (no auth gates it, SCOPE.md: no SMS/OTP for the MVP). That's
    not a theoretical leak: app/router.py's own get_request() treats
    knowing a request's id as the *only* proof needed to view that
    request's precise origin/destination/contact once it's matched (its
    own docstring: the id is "unguessable... and never displayed to
    anyone else -- doubling as proof"). Confirmed real with a live
    TestClient script before writing this fix: a third connection that
    posted nothing received a real match's two ids straight off this
    endpoint, then called GET /requests/{id}?viewer_request_id=<the other
    id from that event> and got back a stranger's full precise pickup/
    dropoff and contact -- exactly the thing SCOPE.md says gets
    "exchanged only between two people after they mutually match -- never
    broadcast," broadcast to a party that was never one of the two.
    Nothing about that exploit needed guessing either id; this endpoint
    handed both of them over for free.

    Fix: the first message a connection sends after opening is the id of
    the one request it's actually watching (app/static/live.js sends it
    right after the socket opens -- by the time that page exists, the
    rider's own id is already known, it was handed back by POST
    /requests). Only a MatchGroup that actually names that id gets
    forwarded; everything else is drained from this connection's own
    queue and dropped. Subscribing to the engine happens *before* waiting
    for that id, not after -- a match involving this connection's own
    request can be produced essentially immediately (scored against
    whatever's already pooled, inside the same event-loop hop that
    processes a brand-new POST), so subscribing first means nothing
    racing in that gap is lost; it just sits in this connection's own
    queue, still in order, until the id arrives and the loop below starts
    checking against it.

    The wait for that registration message is itself bounded by
    REGISTRATION_TIMEOUT_SECONDS. Before this fix it wasn't: a connection
    that opened and then sent nothing at all -- not malformed, just silent,
    which SCOPE.md's no-auth/open-join model lets anyone do with a bare
    WebSocket client, no browser required -- sat in
    `await websocket.receive_json()` forever. engine.subscribe() above had
    already handed it a real queue, and every match found from then on got
    `put()` onto that queue by run_forever() same as any other subscriber's
    -- but with the receive loop permanently stuck waiting on a message
    that was never coming, nothing ever called queue.get() to drain it, so
    every one of those matches just sat there, undelivered and
    undeliverable, for as long as the connection (and the process) stayed
    up. Confirmed real, not theoretical, with a live TestClient script
    before writing this fix: a connection opened and left registered with
    nothing, while three unrelated matches were made elsewhere -- all three
    piled up in that connection's own queue (`qsize() == 3`), and the
    connection itself was still sitting in `engine._subscribers`, neither
    of which a correctly-behaving connection should ever accumulate.
    """
    await websocket.accept()
    engine = websocket.app.state.engine
    queue = engine.subscribe()
    try:
        try:
            registration = await asyncio.wait_for(
                websocket.receive_json(), timeout=REGISTRATION_TIMEOUT_SECONDS
            )
            my_request_id = UUID(str(registration["request_id"]))
        except WebSocketDisconnect:
            return
        except Exception:
            # Malformed/missing registration, or the timeout above firing
            # because none ever arrived -- close rather than leave this
            # connection (and its queue) sitting around forever.
            await websocket.close(code=1008)
            return

        while True:
            match = await queue.get()
            if my_request_id in match.request_ids:
                await websocket.send_json(match.model_dump(mode="json"))
    except WebSocketDisconnect:
        pass
    finally:
        engine.unsubscribe(queue)

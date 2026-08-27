"""Structured intake + privacy-safe read API (TASKS.md #6).

engine and store live on app.state (set up in app/main.py's lifespan), not
as module-level singletons here -- that way each `with TestClient(app) as
client:` block in tests gets a fresh engine/store instead of leaking
matched state between tests.
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect

from app.privacy import to_public
from app.schemas import RideRequest, RideRequestCreate, RideRequestPublic

router = APIRouter()


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


@router.websocket("/matches")
async def stream_matches(websocket: WebSocket) -> None:
    """Streams each MatchGroup as the engine finds it.

    Reads directly off engine.matches (an asyncio.Queue), so with more than
    one connection open, matches are split competing-consumer style across
    them rather than broadcast to all -- fine for this demo's single
    subscriber (TASKS.md #8's simulator/live view); a real fan-out would
    need a per-connection queue, not built speculatively.
    """
    await websocket.accept()
    engine = websocket.app.state.engine
    try:
        while True:
            match = await engine.matches.get()
            await websocket.send_json(match.model_dump(mode="json"))
    except WebSocketDisconnect:
        pass
